from dataclasses import dataclass
from typing import Union

import httpx


class ApiError(Exception):
    pass


@dataclass
class Result[T]:
    status_code: int
    data: T | None

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300


class HttpClient:
    def __init__(self, base_url: str, timeout: int = 10):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def get[T](self, path: str, response_model: type[T]) -> Result[T]:
        async with httpx.AsyncClient(trust_env=False, timeout=self._timeout) as client:
            resp = await client.get(f"{self._base_url}{path}")
            return self._to_result(resp, response_model)

    async def post[T](
        self, path: str, response_model: type[T], json: Union[dict, None] = None
    ) -> Result[T]:
        async with httpx.AsyncClient(trust_env=False, timeout=self._timeout) as client:
            resp = await client.post(f"{self._base_url}{path}", json=json)
            return self._to_result(resp, response_model)

    def _to_result[T](self, resp: httpx.Response, response_model: type[T]) -> Result[T]:
        if resp.is_success:
            return Result(status_code=resp.status_code, data=response_model.model_validate(resp.json()))
        return Result(status_code=resp.status_code, data=None)
