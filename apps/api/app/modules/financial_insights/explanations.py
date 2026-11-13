import hashlib
import json
import logging
import time
from collections import OrderedDict
from collections.abc import Callable
from threading import Lock
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.assistant.exceptions import AssistantError
from app.modules.assistant.providers.base import AssistantProvider
from app.modules.financial_insights.guidance import GUIDANCE, GUIDANCE_VERSION
from app.modules.financial_insights.schemas import FinancialInsightsResponse

logger = logging.getLogger(__name__)
SELECTION_PROMPT = """Você explica alertas financeiros já detectados pelo backend.
Escolha somente códigos de explicações e ações disponíveis para cada alerta.
Não calcule valores, não produza texto livre nem invente causas ou hipóteses.
Não há autorização para executar ações ou alterar dados.
Retorne apenas JSON: {"selections":[{"insight_id":"UUID recebido","explanation_code":"código permitido","action_codes":["código permitido"]}]}.
Inclua cada identificador exatamente uma vez, com uma explicação e de uma a três ações distintas."""


class GuidanceSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    insight_id: UUID
    explanation_code: str = Field(min_length=1, max_length=64)
    action_codes: list[str] = Field(min_length=1, max_length=3)


class GuidanceBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selections: list[GuidanceSelection] = Field(min_length=1, max_length=4)


CacheKey = tuple[UUID, str, str]


class ExplanationCache:
    """Bounded, per-process cache of approved guidance codes, never financial totals."""

    def __init__(
        self,
        *,
        max_entries: int = 256,
        success_ttl: float = 3600,
        failure_ttl: float = 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_entries = max_entries
        self.success_ttl = success_ttl
        self.failure_ttl = failure_ttl
        self.clock = clock
        self.entries: OrderedDict[
            CacheKey, tuple[float, dict[UUID, GuidanceSelection] | None]
        ] = OrderedDict()
        self.inflight: set[CacheKey] = set()
        self.lock = Lock()

    def claim(self, key: CacheKey) -> tuple[bool, dict[UUID, GuidanceSelection] | None]:
        with self.lock:
            if key in self.entries:
                expires, result = self.entries[key]
                if expires > self.clock():
                    self.entries.move_to_end(key)
                    return True, result
                del self.entries[key]
            if key in self.inflight or len(self.inflight) >= self.max_entries:
                return True, None
            self.inflight.add(key)
            return False, None

    def finish(
        self, key: CacheKey, result: dict[UUID, GuidanceSelection] | None
    ) -> None:
        with self.lock:
            self.inflight.discard(key)
            ttl = self.success_ttl if result is not None else self.failure_ttl
            self.entries[key] = (self.clock() + ttl, result)
            self.entries.move_to_end(key)
            while len(self.entries) > self.max_entries:
                self.entries.popitem(last=False)

    def clear(self) -> None:
        with self.lock:
            self.entries.clear()
            self.inflight.clear()


explanation_cache = ExplanationCache()


class InsightExplainer:
    def __init__(
        self, provider: AssistantProvider | None, cache: ExplanationCache, model: str
    ) -> None:
        self.provider = provider
        self.cache = cache
        self.model = model

    def enrich(
        self, response: FinancialInsightsResponse, *, business_id: UUID
    ) -> FinancialInsightsResponse:
        if self.provider is None or not response.insights:
            return response
        # No amounts, dates, personal data or client-supplied descriptions go to the model.
        payload = [
            {
                "insight_id": str(item.id),
                "type": item.type.value,
                "severity": item.severity.value,
                "explanations": GUIDANCE[item.type]["explanations"],
                "actions": GUIDANCE[item.type]["actions"],
            }
            for item in response.insights
        ]
        message = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        digest = hashlib.sha256((GUIDANCE_VERSION + message).encode()).hexdigest()
        key = (business_id, self.model, digest)
        cached, selections = self.cache.claim(key)
        if not cached:
            selections = None
            try:
                raw = self.provider.generate(message, system_prompt=SELECTION_PROMPT)
                batch = GuidanceBatch.model_validate_json(raw)
                expected = {item.id: item for item in response.insights}
                if len(batch.selections) != len(expected):
                    raise ValueError("Incomplete insight selection")
                validated = {}
                for selection in batch.selections:
                    if (
                        selection.insight_id not in expected
                        or selection.insight_id in validated
                    ):
                        raise ValueError("Unexpected or repeated insight")
                    options = GUIDANCE[expected[selection.insight_id].type]
                    if selection.explanation_code not in options["explanations"]:
                        raise ValueError("Invalid explanation")
                    if len(selection.action_codes) != len(
                        set(selection.action_codes)
                    ) or any(
                        code not in options["actions"]
                        for code in selection.action_codes
                    ):
                        raise ValueError("Invalid actions")
                    validated[selection.insight_id] = selection
                selections = validated
            except (AssistantError, ValueError, TypeError):
                # Never log model text, prompts, amounts, exception messages or credentials.
                logger.info(
                    "Financial insight guidance unavailable; deterministic fallback"
                )
            finally:
                self.cache.finish(key, selections)
        if selections is not None:
            for item in response.insights:
                selected = selections[item.id]
                options = GUIDANCE[item.type]
                item.explanation = options["explanations"][selected.explanation_code]
                item.suggested_actions = [
                    options["actions"][code] for code in selected.action_codes
                ]
                item.explanation_source = "gemini"
        return response
