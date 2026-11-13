import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Event
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.modules.assistant.exceptions import AssistantUnavailableError
from app.modules.financial_insights.explanations import (
    ExplanationCache,
    InsightExplainer,
)
from app.modules.financial_insights.guidance import GUIDANCE, default_guidance
from app.modules.financial_insights.schemas import (
    FinancialInsight,
    FinancialInsightsResponse,
    InsightPeriod,
    InsightSeverity,
    InsightType,
    InsightValues,
)

BUSINESS = uuid4()
INSIGHT = uuid4()


def response(*, income="70.00", second=False):
    period = InsightPeriod(start_date=date(2026, 11, 1), end_date=date(2026, 11, 13))
    previous = InsightPeriod(start_date=date(2026, 10, 1), end_date=date(2026, 10, 13))
    explanation, actions = default_guidance(InsightType.REVENUE_DROP)
    insights = [
        FinancialInsight(
            id=INSIGHT,
            type=InsightType.REVENUE_DROP,
            title="Backend title",
            description=f"Backend facts: {income}",
            period=period,
            comparison_period=previous,
            values=InsightValues(
                paid_income=Decimal(income), previous_paid_income=Decimal(100)
            ),
            variation_percentage=Decimal(-30),
            severity=InsightSeverity.WARNING,
            reference_date=date(2026, 11, 13),
            explanation=explanation,
            suggested_actions=actions,
        )
    ]
    if second:
        explanation, actions = default_guidance(InsightType.OVERDUE_EXPENSES)
        insights.append(
            FinancialInsight(
                id=uuid4(),
                type=InsightType.OVERDUE_EXPENSES,
                title="Overdue",
                description="Backend overdue facts",
                period=period,
                values=InsightValues(overdue_amount=Decimal(20), overdue_count=1),
                severity=InsightSeverity.WARNING,
                reference_date=date(2026, 11, 13),
                explanation=explanation,
                suggested_actions=actions,
            )
        )
    return FinancialInsightsResponse(
        reference_date=date(2026, 11, 13),
        timezone="America/Fortaleza",
        period=period,
        comparison_period=previous,
        is_partial=True,
        insights=insights,
    )


def choose(message, **kwargs):
    payload = json.loads(message)
    return json.dumps(
        {
            "selections": [
                {
                    "insight_id": item["insight_id"],
                    "explanation_code": list(item["explanations"])[-1],
                    "action_codes": list(item["actions"])[-2:],
                }
                for item in payload
            ]
        }
    )


def explainer(provider=None, cache=None):
    provider = provider or Mock()
    provider.generate.side_effect = choose
    return InsightExplainer(provider, cache or ExplanationCache(), "offline-model")


def test_ai_selects_only_approved_guidance_and_never_changes_backend_facts():
    service = explainer()
    original = response(second=True)
    before = original.model_dump(exclude={"insights"})
    facts = [
        item.model_dump(
            exclude={"explanation", "suggested_actions", "explanation_source"}
        )
        for item in original.insights
    ]
    result = service.enrich(original, business_id=BUSINESS)
    assert result.model_dump(exclude={"insights"}) == before
    assert [
        item.model_dump(
            exclude={"explanation", "suggested_actions", "explanation_source"}
        )
        for item in result.insights
    ] == facts
    assert all(item.explanation_source == "gemini" for item in result.insights)
    for item in result.insights:
        assert item.explanation in GUIDANCE[item.type]["explanations"].values()
        assert all(
            action in GUIDANCE[item.type]["actions"].values()
            for action in item.suggested_actions
        )
    service.provider.generate.assert_called_once()
    message = service.provider.generate.call_args.args[0]
    assert (
        "paid_income" not in message
        and "70.00" not in message
        and "100.00" not in message
    )
    assert str(BUSINESS) not in message and "Backend facts" not in message
    assert "system_prompt" in service.provider.generate.call_args.kwargs


@pytest.mark.parametrize(
    "invalid",
    [
        "text",
        "fenced",
        "extra_batch",
        "extra_selection",
        "invented_explanation",
        "unknown_action",
        "foreign_action",
        "duplicate_actions",
        "duplicate_ids",
        "wrong_id",
        "empty_selection",
        "empty_actions",
        "too_many_actions",
    ],
)
def test_untrusted_model_output_falls_back_without_fabricated_values(invalid):
    provider = Mock()
    original = response(second=invalid == "duplicate_ids")

    def malicious(message, **kwargs):
        batch = json.loads(choose(message))
        first = batch["selections"][0]
        if invalid == "text":
            return "Invented private cause and value 999999."
        if invalid == "fenced":
            return "```json\n" + json.dumps(batch) + "\n```"
        if invalid == "extra_batch":
            batch["financial_result"] = "999999"
        elif invalid == "extra_selection":
            first["explanation"] = "Invented cause"
        elif invalid == "invented_explanation":
            first["explanation_code"] = "invented_cause"
        elif invalid in ("unknown_action", "foreign_action"):
            first["action_codes"] = [
                "execute_transfer"
                if invalid == "unknown_action"
                else "contact_suppliers"
            ]
        elif invalid == "duplicate_actions":
            first["action_codes"] *= 1
            first["action_codes"] = [first["action_codes"][0]] * 2
        elif invalid == "duplicate_ids":
            batch["selections"][1] = first.copy()
        elif invalid == "wrong_id":
            first["insight_id"] = str(uuid4())
        elif invalid == "empty_selection":
            batch["selections"] = []
        elif invalid == "empty_actions":
            first["action_codes"] = []
        elif invalid == "too_many_actions":
            first["action_codes"] *= 2
        return json.dumps(batch)

    provider.generate.side_effect = malicious
    service = InsightExplainer(provider, ExplanationCache(), "offline-model")
    result = service.enrich(original, business_id=BUSINESS)
    assert all(item.explanation_source == "deterministic" for item in result.insights)
    assert result.insights[0].values.paid_income == Decimal(70)
    assert "Invented" not in result.model_dump_json()
    provider.generate.assert_called_once()


def test_cached_guidance_reuses_codes_while_amounts_stay_fresh():
    service = explainer()
    first = service.enrich(response(), business_id=BUSINESS)
    second = service.enrich(response(income="60.00"), business_id=BUSINESS)
    assert first.insights[0].explanation == second.insights[0].explanation
    assert second.insights[0].values.paid_income == Decimal(60)
    assert second.insights[0].description == "Backend facts: 60.00"
    assert second.insights[0].explanation_source == "gemini"
    service.provider.generate.assert_called_once()


def test_cache_does_not_share_between_businesses_models_or_alert_shapes():
    cache = ExplanationCache()
    service = explainer(cache=cache)
    service.enrich(response(), business_id=BUSINESS)
    service.enrich(response(), business_id=uuid4())
    service.model = "another-model"
    service.enrich(response(), business_id=BUSINESS)
    service.enrich(response(second=True), business_id=BUSINESS)
    assert service.provider.generate.call_count == 4


def test_success_cache_expires_and_is_bounded():
    clock = [0.0]
    cache = ExplanationCache(max_entries=2, success_ttl=10, clock=lambda: clock[0])
    service = explainer(cache=cache)
    service.enrich(response(), business_id=BUSINESS)
    clock[0] = 9
    service.enrich(response(), business_id=BUSINESS)
    assert service.provider.generate.call_count == 1
    clock[0] = 10
    service.enrich(response(), business_id=BUSINESS)
    assert service.provider.generate.call_count == 2
    service.enrich(response(), business_id=uuid4())
    service.enrich(response(), business_id=uuid4())
    assert len(cache.entries) == 2
    service.enrich(response(), business_id=BUSINESS)
    assert service.provider.generate.call_count == 5


def test_failure_cooldown_and_logs_exclude_private_data(caplog):
    clock = [0.0]
    cache = ExplanationCache(failure_ttl=3, clock=lambda: clock[0])
    provider = Mock()
    provider.generate.side_effect = AssistantUnavailableError(
        "PRIVATE_API_KEY_AND_MESSAGE"
    )
    service = InsightExplainer(provider, cache, "offline-model")
    with caplog.at_level(logging.INFO):
        result = service.enrich(response(), business_id=BUSINESS)
        service.enrich(response(), business_id=BUSINESS)
    assert result.insights[0].explanation_source == "deterministic"
    provider.generate.assert_called_once()
    assert "PRIVATE" not in caplog.text and "70.00" not in caplog.text
    clock[0] = 3
    provider.generate.side_effect = choose
    result = service.enrich(response(), business_id=BUSINESS)
    assert provider.generate.call_count == 2
    assert result.insights[0].explanation_source == "gemini"


def test_simultaneous_same_snapshot_does_not_duplicate_model_calls():
    started, release = Event(), Event()
    provider = Mock()

    def delayed(message, **kwargs):
        started.set()
        assert release.wait(3)
        return choose(message)

    provider.generate.side_effect = delayed
    service = InsightExplainer(provider, ExplanationCache(), "offline-model")
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(service.enrich, response(), business_id=BUSINESS)
        try:
            assert started.wait(3)
            concurrent = service.enrich(response(), business_id=BUSINESS)
            assert concurrent.insights[0].explanation_source == "deterministic"
            provider.generate.assert_called_once()
        finally:
            release.set()
        assert future.result(timeout=3).insights[0].explanation_source == "gemini"
    assert (
        service.enrich(response(), business_id=BUSINESS).insights[0].explanation_source
        == "gemini"
    )
    provider.generate.assert_called_once()


def test_no_provider_or_no_insights_needs_no_generation():
    provider = Mock()
    cache = ExplanationCache()
    assert (
        InsightExplainer(None, cache, "offline")
        .enrich(response(), business_id=BUSINESS)
        .insights[0]
        .explanation_source
        == "deterministic"
    )
    empty = response()
    empty.insights.clear()
    assert (
        InsightExplainer(provider, cache, "offline")
        .enrich(empty, business_id=BUSINESS)
        .insights
        == []
    )
    provider.generate.assert_not_called()
