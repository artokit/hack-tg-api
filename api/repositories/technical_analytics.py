from dataclasses import dataclass
from datetime import datetime
from math import isfinite

import httpx


class PrometheusUnavailable(Exception):
    pass


@dataclass(frozen=True)
class MetricSample:
    labels: dict[str, str]
    value: float


class PrometheusRepository:
    def __init__(self, client: httpx.AsyncClient):
        self._client = client

    async def query(self, expression: str, at: datetime) -> list[MetricSample]:
        try:
            response = await self._client.get("api/v1/query", params={
                "query": expression, "time": at.isoformat(),
            })
            response.raise_for_status()
            payload = response.json()
            if payload["status"] != "success" or payload["data"]["resultType"] != "vector":
                raise PrometheusUnavailable
            samples = [MetricSample(item["metric"], float(item["value"][1])) for item in payload["data"]["result"]]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as error:
            raise PrometheusUnavailable from error
        return [sample for sample in samples if isfinite(sample.value)]
