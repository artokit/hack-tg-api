from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


TechnicalRange = Literal["1h", "24h", "7d"]


class ModelTokensRead(BaseModel):
    model: str
    input: int
    output: int


class WorkloadTokensRead(BaseModel):
    input: int
    output: int
    by_model: list[ModelTokensRead]


class TechnicalTokensRead(BaseModel):
    chat: WorkloadTokensRead


class ResponseTimeRead(BaseModel):
    sample_count: int
    mean_ms: float | None
    p95_ms: float | None


class TechnicalStageRead(BaseModel):
    stage: Literal["queue", "preparation", "search", "generation", "delivery"]
    mean_ms: float | None


class ResponseBreakdownRead(BaseModel):
    sample_count: int
    mean_ms: float | None
    stages: list[TechnicalStageRead]


class AgentStepRead(BaseModel):
    kind: Literal["model", "tool", "rag"]
    name: str
    mean_ms: float


class DeliveryOutcomesRead(BaseModel):
    sent: int = 0
    failed: int = 0
    unknown: int = 0


class TechnicalDeliveryRead(BaseModel):
    answer: DeliveryOutcomesRead
    fallback: DeliveryOutcomesRead
    service: DeliveryOutcomesRead


class RequestAnalyticsRead(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{
        "range": "24h",
        "from_at": "2026-11-14T10:00:00Z",
        "to_at": "2026-11-15T10:00:00Z",
        "tokens": {"chat": {"input": 0, "output": 0, "by_model": []}},
        "response_time": {"sample_count": 0, "mean_ms": None, "p95_ms": None},
        "stages": [{"stage": stage, "mean_ms": None} for stage in ("queue", "preparation", "delivery")],
        "response_breakdown": {"sample_count": 0, "mean_ms": None, "stages": [
            {"stage": stage, "mean_ms": None}
            for stage in ("queue", "preparation", "search", "generation", "delivery")
        ]},
        "agent_breakdown": [],
        "delivery": {kind: {"sent": 0, "failed": 0, "unknown": 0} for kind in ("answer", "fallback", "service")},
    }]})

    range: TechnicalRange
    from_at: datetime
    to_at: datetime
    tokens: TechnicalTokensRead
    response_time: ResponseTimeRead
    stages: list[TechnicalStageRead]
    response_breakdown: ResponseBreakdownRead
    agent_breakdown: list[AgentStepRead]
    delivery: TechnicalDeliveryRead
