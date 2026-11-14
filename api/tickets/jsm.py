import httpx

from tickets.base import TicketRequest, TicketSystem


class TicketSystemError(Exception):
    """Ошибка на стороне тикет-системы (плохие данные, нет доступа и т.п.)."""


def _ensure_success(resp: httpx.Response) -> None:
    """Превращает любую HTTP-ошибку (включая сетевые) в доменную TicketSystemError."""
    if resp.is_success:
        return
    try:
        body = resp.json()
    except Exception:
        body = resp.text
    raise TicketSystemError(f"JSM error {resp.status_code}: {body}")


class JsmAdapter(TicketSystem):
    """DAL-слой: транслирует заявку в Jira Service Management customer request.

    Auth: Basic, email + API token (создаётся в настройках аккаунта Atlassian).
    """

    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        service_desk_id: str,
        request_type_id: str,
    ):
        self._http = httpx.AsyncClient(
            base_url=base_url,
            auth=(email, api_token),
            headers={"Accept": "application/json"},
            timeout=30,
        )
        self._sd = service_desk_id
        self._rt = request_type_id

    async def create(self, req: TicketRequest) -> None:
        payload = {
            # JSM API требует строки, не числа
            "serviceDeskId": self._sd,
            "requestTypeId": self._rt,
            "requestFieldValues": {
                "summary": req.title,        # у нас title, у Jira summary
                "description": req.description,
            },
        }
        resp = await self._http.post(
            "/rest/servicedeskapi/request",
            json=payload,
        )
        if resp.status_code in (400, 403):
            # 400: не хватает обязательных полей типа заявки; 403: юзер не customer этого Service Desk
            raise TicketSystemError(f"JSM rejected request: {resp.json()}")
        _ensure_success(resp)
