import httpx

from tickets.base import TicketAttachment, TicketCreated, TicketRequest, TicketSystem


class TicketSystemError(Exception):
    """Ошибка на стороне тикет-системы (плохие данные, нет доступа и т.п.)."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


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
            if resp.status_code in (400, 403):
                # 400: не хватает обязательных полей типа заявки; 403: юзер не customer этого Service Desk
                raise TicketSystemError(f"JSM rejected request: {resp.json()}")
            _ensure_success(resp)
            body = resp.json()
            external_id = body["issueId"]
            external_key = body["issueKey"]
            if not isinstance(external_id, str) or not external_id.isdigit():
                raise ValueError("Invalid issue ID")
            if not isinstance(external_key, str) or not external_key:
                raise ValueError("Invalid issue key")
        except httpx.RequestError as error:
            raise TicketSystemError("Не удалось выполнить запрос к Jira") from error
        except (KeyError, TypeError, ValueError) as error:
            raise TicketSystemError("Jira вернула некорректный ответ") from error
        return TicketCreated(external_id=external_id, external_key=external_key)

    async def attach_file(
        self,
        issue_id_or_key: str,
        filename: str,
        content: bytes,
        content_type: str,
        public: bool,
    ) -> TicketAttachment:
        try:
            request = await self._http.get(
                f"/rest/servicedeskapi/request/{issue_id_or_key}"
            )
            self._ensure_attachment_success(request)
            service_desk_id = request.json()["serviceDeskId"]
            if not isinstance(service_desk_id, str) or not service_desk_id.isdigit():
                raise ValueError("Invalid service desk ID")

            upload = await self._http.post(
                f"/rest/servicedeskapi/servicedesk/{service_desk_id}/attachTemporaryFile",
                headers={"X-Atlassian-Token": "no-check"},
                files={"file": (filename, content, content_type)},
            )
            self._ensure_attachment_success(upload)
            temporary_id = upload.json()["temporaryAttachments"][0]["temporaryAttachmentId"]
            if not isinstance(temporary_id, str) or not temporary_id:
                raise ValueError("Invalid temporary attachment ID")

            attached = await self._http.post(
                f"/rest/servicedeskapi/request/{issue_id_or_key}/attachment",
                json={"public": public, "temporaryAttachmentIds": [temporary_id]},
            )
            self._ensure_attachment_success(attached)
            comment_id = attached.json()["comment"]["id"]
            if not isinstance(comment_id, str) or not comment_id:
                raise ValueError("Invalid comment ID")
        except httpx.RequestError as error:
            raise TicketSystemError("Не удалось выполнить запрос к Jira") from error
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise TicketSystemError("Jira вернула некорректный ответ") from error

        return TicketAttachment(
            issue_id_or_key=issue_id_or_key,
            comment_id=comment_id,
            filename=filename,
            public=public,
        )

    @staticmethod
    def _ensure_attachment_success(response: httpx.Response) -> None:
        if response.status_code == 404:
            raise TicketSystemError("Заявка или сервис-деск Jira не найдены", 404)
        if response.status_code == 400:
            raise TicketSystemError("Jira отклонила прикрепление файла", 400)
        if response.status_code == 413:
            raise TicketSystemError("Файл превышает ограничение Jira", 413)
        if not response.is_success:
            raise TicketSystemError(
                f"Ошибка прикрепления файла в Jira: HTTP {response.status_code}"
            )
