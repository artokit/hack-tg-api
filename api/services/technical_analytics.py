import asyncio
from datetime import UTC, datetime, timedelta

from repositories.technical_analytics import MetricSample, PrometheusRepository, PrometheusUnavailable
from schemas.technical_analytics import (
    AgentStepRead,
    DeliveryOutcomesRead,
    ModelTokensRead,
    ResponseTimeRead,
    TechnicalAnalyticsRead,
    TechnicalDeliveryRead,
    TechnicalRange,
    TechnicalStageRead,
    TechnicalTokensRead,
    WorkloadTokensRead,
)


WINDOWS = {"1h": timedelta(hours=1), "24h": timedelta(days=1), "7d": timedelta(days=7)}
REPLY_DURATION = "bars_telegram_reply_duration_seconds"


class TechnicalAnalyticsUnavailable(Exception):
    pass


def summed_increase(metric: str, window: str, labels: str, selector: str = "") -> str:
    return f"sum by ({labels}) (increase({metric}{selector}[{window}] anchored))"


def mean_duration(metric: str, window: str, label: str, selector: str = "") -> str:
    total = summed_increase(f"{metric}_sum", window, label, selector)
    count = summed_increase(f"{metric}_count", window, label, selector)
    return f"({total}) / ({count})"


def workload_tokens(samples: list[MetricSample], workload: str) -> WorkloadTokensRead:
    models: dict[str, dict[str, int]] = {}
    for sample in samples:
        if sample.labels.get("workload") != workload:
            continue
        counts = models.setdefault(sample.labels["model"], {"input": 0, "output": 0})
        counts[sample.labels["direction"]] = round(sample.value)
    by_model = [ModelTokensRead(model=model, **counts) for model, counts in sorted(models.items())]
    return WorkloadTokensRead(
        input=sum(item.input for item in by_model), output=sum(item.output for item in by_model), by_model=by_model,
    )


def delivery_outcomes(samples: list[MetricSample], kind: str) -> DeliveryOutcomesRead:
    return DeliveryOutcomesRead(**{
        sample.labels["status"]: round(sample.value) for sample in samples if sample.labels.get("kind") == kind
    })


def milliseconds(value: float | None) -> float | None:
    return round(value * 1000, 2) if value is not None else None


class TechnicalAnalyticsService:
    def __init__(self, repository: PrometheusRepository | None):
        self._repository = repository

    async def read(self, window: TechnicalRange) -> TechnicalAnalyticsRead:
        if self._repository is None:
            raise TechnicalAnalyticsUnavailable
        now = datetime.now(UTC)
        queries = (
            summed_increase("bars_model_tokens_total", window, "workload, model, direction"),
            mean_duration(REPLY_DURATION, window, "stage"),
            f'sum(increase({REPLY_DURATION}_count{{stage="total"}}[{window}] anchored))',
            f'histogram_quantile(0.95, sum by (le) (increase({REPLY_DURATION}_bucket{{stage="total"}}[{window}] anchored)))',
            mean_duration("bars_model_duration_seconds", window, "model", '{workload="chat"}'),
            mean_duration("gen_ai_execute_tool_duration_seconds", window, "gen_ai_tool_name", '{gen_ai_agent_name="Bars"}'),
            mean_duration("bars_rag_step_duration_seconds", window, "step"),
            summed_increase("bars_telegram_delivery_count_total", window, "kind, status"),
        )
        try:
            tokens, durations, count, p95, models, tools, rag, deliveries = await asyncio.gather(*(
                self._repository.query(query, now) for query in queries
            ))
        except PrometheusUnavailable as error:
            raise TechnicalAnalyticsUnavailable from error
        durations_by_stage = {sample.labels["stage"]: sample.value for sample in durations}
        breakdown = [
            AgentStepRead(kind=kind, name=sample.labels[label], mean_ms=round(sample.value * 1000, 2))
            for kind, label, samples in (("model", "model", models), ("tool", "gen_ai_tool_name", tools), ("rag", "step", rag))
            for sample in sorted(samples, key=lambda item: item.labels[label])
        ]
        return TechnicalAnalyticsRead(
            range=window,
            from_at=now - WINDOWS[window],
            to_at=now,
            tokens=TechnicalTokensRead(
                chat=workload_tokens(tokens, "chat"), document_import=workload_tokens(tokens, "document_import"),
            ),
            response_time=ResponseTimeRead(
                sample_count=round(count[0].value) if count else 0,
                mean_ms=milliseconds(durations_by_stage.get("total")),
                p95_ms=milliseconds(p95[0].value) if p95 else None,
            ),
            stages=[
                TechnicalStageRead(stage=stage, mean_ms=milliseconds(durations_by_stage.get(stage)))
                for stage in ("queue", "preparation", "delivery")
            ],
            agent_breakdown=breakdown,
            delivery=TechnicalDeliveryRead(
                answer=delivery_outcomes(deliveries, "answer"),
                fallback=delivery_outcomes(deliveries, "fallback"),
                service=delivery_outcomes(deliveries, "service"),
            ),
        )
