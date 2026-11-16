import hashlib
import json
import logging
import re
import time
from collections import OrderedDict
from collections.abc import Callable
from decimal import Decimal
from threading import Lock
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.modules.assistant.exceptions import AssistantError
from app.modules.assistant.providers.base import AssistantProvider
from app.modules.financial_insights.schemas import (
    FinancialInsight,
    FinancialInsightsResponse,
)
from app.modules.financial_insights.service import money

logger = logging.getLogger(__name__)
EXPLANATION_VERSION = "2"
PLACEHOLDER = re.compile(r"\{\{([a-z_]+)\}\}")
DATE_FACTS = {"period", "comparison_period", "reference_date"}
EXPLANATION_PROMPT = """Você explica alertas financeiros já identificados pelo backend.
Receberá fatos autorizados de cada alerta: tipo, severidade, períodos, valores realizados,
variação já calculada e data de referência. Escreva em português brasileiro, com clareza.
Produza uma explicação de até duas frases e de uma a três sugestões práticas distintas.
Use somente os fatos recebidos. Não calcule, estime, arredonde ou invente valores,
percentuais, datas, causas ou características da empresa. Não confunda receitas recebidas
com valores pendentes, nem resultado financeiro realizado com lucro contábil.
Para receitas e despesas, considere os períodos comparados e se o mês está parcial.
Despesas vencidas abrangem todas as datas anteriores à referência, independentemente
do mês selecionado. Não presuma que uma pendência já foi paga fora do sistema.
A explicação deve descrever fatos e suas implicações; nunca atribuir uma causa sem evidência.
Sugestões para investigar causas devem ser condicionais: 'verifique se', 'confira se'.
Não apresente hipóteses como fatos nem prometa resultados. Nenhuma ação será executada.
Para mencionar qualquer valor, percentual, contagem ou período, use SOMENTE marcadores
com nomes de facts, como {{paid_income}}, {{variation_percentage}} ou {{period}}.
Os marcadores já incluem moeda, porcentagem e datas formatadas; não acrescente unidades.
O backend substituirá os marcadores pelos dados corretos. Não escreva números literais,
URLs, HTML ou marcadores que não existam nos fatos daquele alerta.
Na explicação, inclua ao menos um marcador financeiro e um marcador de período ou data.
Retorne apenas JSON no formato:
{"explanations":[{"insight_id":"UUID recebido","explanation":"Texto com {{period}} e um marcador financeiro válido","suggested_actions":["Sugestão prática"]}]}.
Inclua cada identificador recebido exatamente uma vez; não acrescente outros campos."""

ExplanationText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=10, max_length=1000)
]
ActionText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=10, max_length=350)
]


class GeneratedExplanation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    insight_id: UUID
    explanation: ExplanationText
    suggested_actions: list[ActionText] = Field(min_length=1, max_length=3)


class ExplanationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    explanations: list[GeneratedExplanation] = Field(min_length=1, max_length=4)


def insight_facts(insight: FinancialInsight) -> dict[str, str]:
    facts = {
        "period": (
            f"{insight.period.start_date:%d/%m/%Y} a {insight.period.end_date:%d/%m/%Y}"
        ),
        "reference_date": f"{insight.reference_date:%d/%m/%Y}",
    }
    if insight.comparison_period is not None:
        facts["comparison_period"] = (
            f"{insight.comparison_period.start_date:%d/%m/%Y} a "
            f"{insight.comparison_period.end_date:%d/%m/%Y}"
        )
    for name, value in insight.values.model_dump(exclude_none=True).items():
        facts[name] = money(value) if isinstance(value, Decimal) else str(value)
    if insight.variation_percentage is not None:
        facts["variation_percentage"] = (
            str(insight.variation_percentage).replace(".", ",") + "%"
        )
    return facts


def render_text(template: str, facts: dict[str, str]) -> str:
    references = set(PLACEHOLDER.findall(template))
    if not references.issubset(facts):
        raise ValueError("Unknown financial fact")
    remaining = PLACEHOLDER.sub("", template)
    # Only the backend may insert numbers; unknown braces and markup are invalid.
    if re.search(r"[\d{}<>]|https?://|www\.", remaining, flags=re.IGNORECASE):
        raise ValueError("Untrusted literal or markup")
    return PLACEHOLDER.sub(lambda match: facts[match[1]], template)


def render_explanation(
    generated: GeneratedExplanation, facts: dict[str, str]
) -> tuple[str, list[str]]:
    references = set(PLACEHOLDER.findall(generated.explanation))
    if not references.intersection(DATE_FACTS) or not references.difference(DATE_FACTS):
        raise ValueError("Explanation must reference financial and period facts")
    actions = generated.suggested_actions
    if len({action.casefold() for action in actions}) != len(actions):
        raise ValueError("Repeated actions")
    explanation = render_text(generated.explanation, facts)
    rendered_actions = [render_text(action, facts) for action in actions]
    if len({action.casefold() for action in rendered_actions}) != len(rendered_actions):
        raise ValueError("Repeated rendered actions")
    return explanation, rendered_actions


CacheKey = tuple[UUID, str, str]


class ExplanationCache:
    """Bounded per-process cache of validated templates, keyed by authorized facts."""

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
            CacheKey, tuple[float, dict[UUID, GeneratedExplanation] | None]
        ] = OrderedDict()
        self.inflight: set[CacheKey] = set()
        self.lock = Lock()

    def claim(
        self, key: CacheKey
    ) -> tuple[bool, dict[UUID, GeneratedExplanation] | None]:
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
        self, key: CacheKey, result: dict[UUID, GeneratedExplanation] | None
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
        # Send aggregates only, never business/user identifiers or record descriptions.
        facts = {item.id: insight_facts(item) for item in response.insights}
        payload = [
            {
                "insight_id": str(item.id),
                "type": item.type.value,
                "severity": item.severity.value,
                "is_partial": response.is_partial,
                "timezone": response.timezone,
                "facts": facts[item.id],
            }
            for item in response.insights
        ]
        message = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        # Values and periods now affect the explanation: every fact must affect its key.
        digest = hashlib.sha256((EXPLANATION_VERSION + message).encode()).hexdigest()
        key = (business_id, self.model, digest)
        cached, explanations = self.cache.claim(key)
        if not cached:
            explanations = None
            try:
                raw = self.provider.generate(message, system_prompt=EXPLANATION_PROMPT)
                batch = ExplanationBatch.model_validate_json(raw)
                if len(batch.explanations) != len(facts):
                    raise ValueError("Incomplete insight explanations")
                validated = {}
                for generated in batch.explanations:
                    if (
                        generated.insight_id not in facts
                        or generated.insight_id in validated
                    ):
                        raise ValueError("Unexpected or repeated insight")
                    render_explanation(generated, facts[generated.insight_id])
                    validated[generated.insight_id] = generated
                explanations = validated
            except (AssistantError, ValueError, TypeError):
                # Never log model text, prompts, amounts, exception messages or credentials.
                logger.info(
                    "Financial insight explanation unavailable; deterministic fallback"
                )
            finally:
                self.cache.finish(key, explanations)
        if explanations is not None:
            rendered = {
                identifier: render_explanation(generated, facts[identifier])
                for identifier, generated in explanations.items()
            }
            for item in response.insights:
                item.explanation, item.suggested_actions = rendered[item.id]
                item.explanation_source = "gemini"
        return response
