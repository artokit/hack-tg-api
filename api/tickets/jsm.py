import re

import httpx

from tickets.base import TicketRequest, TicketSystem


class TicketSystemError(Exception):
    """Ошибка на стороне тикет-системы (плохие данные, нет доступа и т.п.)."""


class TicketCreationUncertain(TicketSystemError):
    pass


class TicketCreationDeferred(TicketSystemError):
    pass


class TicketAttachmentRejected(TicketSystemError):
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


def _ensure_attachment_success(resp: httpx.Response) -> None:
    if resp.status_code in (400, 401, 403, 413, 415, 422):
        raise TicketAttachmentRejected(f"JSM rejected attachment with status {resp.status_code}")
    _ensure_success(resp)


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

    async def create(self, req: TicketRequest) -> str:
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
            resp = await self._http.post("/rest/servicedeskapi/request", json=payload)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as error:
            raise TicketCreationDeferred("JSM connection unavailable") from error
        except httpx.HTTPError as error:
            raise TicketCreationUncertain("JSM did not confirm ticket creation") from error
        if resp.status_code == 429:
            raise TicketCreationDeferred("JSM rate limit exceeded")
        if resp.status_code >= 500 or resp.status_code == 408:
            raise TicketCreationUncertain(f"JSM did not confirm ticket creation ({resp.status_code})")
        _ensure_success(resp)
        try:
            key = resp.json()["issueKey"]
            if isinstance(key, str) and re.fullmatch(r"[A-Z][A-Z0-9_]*-[0-9]+", key):
                return key
        except (ValueError, KeyError, TypeError) as error:
            raise TicketCreationUncertain("JSM response is missing an issue key") from error
        raise TicketCreationUncertain("JSM response contains an invalid issue key")

    async def find_by_reference(self, reference: str) -> str | None:
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
        key = issue["key"]
        if reference in str(issue.get("fields", {}).get("description")) and re.fullmatch(
            r"[A-Z][A-Z0-9_]*-[0-9]+", key,
        ):
            return key
        return None

    async def attach_internal(self, issue_key: str, filename: str, content: bytes) -> None:
        path = f"/rest/servicedeskapi/request/{issue_key}/attachment"
        start = 0
        while True:
            response = await self._http.get(path, params={"start": start, "limit": 50})
            _ensure_attachment_success(response)
            page = response.json()
            if any(value["filename"] == filename for value in page["values"]):
                return
            if page["isLastPage"]:
                break
            start += page["size"]
            if page["size"] <= 0:
                raise TicketSystemError("Invalid Jira attachment page")

        upload = await self._http.post(
            f"/rest/servicedeskapi/servicedesk/{self._sd}/attachTemporaryFile",
            files={"file": (filename, content, "text/plain; charset=utf-8")},
            headers={"X-Atlassian-Token": "no-check", "X-ExperimentalApi": "opt-in"},
        )
        _ensure_attachment_success(upload)
        attachment_id = upload.json()["temporaryAttachments"][0]["temporaryAttachmentId"]
        response = await self._http.post(path, json={
            "temporaryAttachmentIds": [attachment_id],
            "public": False,
        })
        _ensure_attachment_success(response)
