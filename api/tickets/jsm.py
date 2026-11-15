import re

import httpx

from tickets.base import TicketCreated, TicketRequest, TicketSystem


class TicketSystemError(Exception):
    """Ошибка на стороне тикет-системы (плохие данные, нет доступа и т.п.)."""


class TicketCreationDeferred(TicketSystemError):
    pass


class TicketCreationUncertain(TicketSystemError):
    pass


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

    async def create(self, req: TicketRequest) -> TicketCreated:
        payload = {
            # JSM API требует строки, не числа
            "serviceDeskId": self._sd,
            "requestTypeId": self._rt,
            "requestFieldValues": {
                "summary": req.title,        # у нас title, у Jira summary
                "description": req.description,
            },
        }
        try:
            resp = await self._http.post(
                "/rest/servicedeskapi/request",
                json=payload,
            )
            if resp.status_code == 429:
                raise TicketCreationDeferred("JSM rate limit exceeded")
            if resp.status_code >= 500 or resp.status_code == 408:
                raise TicketCreationUncertain(f"JSM did not confirm ticket creation ({resp.status_code})")
            _ensure_success(resp)
            body = resp.json()
            external_id = body["issueId"]
            external_key = body["issueKey"]
            if not isinstance(external_id, str) or not external_id.isdigit():
                raise ValueError("Invalid issue ID")
            if not isinstance(external_key, str) or not external_key:
                raise ValueError("Invalid issue key")
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as error:
            raise TicketCreationDeferred("Не удалось подключиться к Jira") from error
        except httpx.RequestError as error:
            raise TicketCreationUncertain("Jira не подтвердила создание заявки") from error
        except (KeyError, TypeError, ValueError) as error:
            raise TicketCreationUncertain("Jira вернула некорректный ответ") from error
        return TicketCreated(external_id=external_id, external_key=external_key)

    async def find_by_reference(self, reference: str) -> TicketCreated | None:
        if not re.fullmatch(r"BARSREQ[0-9a-f]{32}", reference):
            raise ValueError("Invalid support request reference")
        response = await self._http.post("/rest/api/3/search/jql", json={
            "jql": f'description ~ "{reference}"',
            "fields": ["description"],
            "maxResults": 2,
        })
        _ensure_success(response)
        result = response.json()
        issues = result["issues"]
        if len(issues) != 1 or result.get("nextPageToken"):
            return None
        issue = issues[0]
        if reference not in str(issue.get("fields", {}).get("description")):
            return None
        external_id, external_key = issue["id"], issue["key"]
        if not isinstance(external_id, str) or not external_id.isdigit():
            raise ValueError("Invalid issue ID")
        if not isinstance(external_key, str) or not external_key:
            raise ValueError("Invalid issue key")
        return TicketCreated(external_id=external_id, external_key=external_key)
