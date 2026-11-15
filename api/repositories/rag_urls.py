import asyncio
import socket
from email.message import Message
from ipaddress import IPv6Address, ip_address, ip_network
from pathlib import PurePosixPath
from urllib.parse import unquote

import httpx

from models.rag import InvalidDocument, RagUnavailable
from repositories.rag_files import DOCUMENT_FORMATS, read_document


CONTENT_FORMATS = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/markdown": "md",
}
IPV6_INTERNET = ip_network("2000::/3")


async def public_address(url: httpx.URL) -> str:
    if (
        url.scheme not in ("http", "https") or not url.host or url.userinfo
        or url.port not in (None, 80 if url.scheme == "http" else 443)
    ):
        raise InvalidDocument("invalid_source_url")
    port = url.port or (443 if url.scheme == "https" else 80)
    targets = await asyncio.get_running_loop().getaddrinfo(
        url.raw_host.decode("ascii"), port, type=socket.SOCK_STREAM,
    )
    addresses = [ip_address(target[4][0]) for target in targets]
    if not addresses or any(
        not address.is_global or address.is_multicast
        or isinstance(address, IPv6Address) and (
            address not in IPV6_INTERNET or address.sixtofour is not None or address.teredo is not None
        )
        for address in addresses
    ):
        raise InvalidDocument("invalid_source_url")
    return str(next((address for address in addresses if address.version == 4), addresses[0]))


async def load_url(source_url: str) -> tuple[bytes, str, str]:
    url = httpx.URL(source_url)
    try:
        async with asyncio.timeout(60):
            for _ in range(5):
                address = await public_address(url)
                async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
                    async with client.stream(
                        "GET", url.copy_with(host=address),
                        headers={"Host": url.raw_host.decode("ascii"), "Accept-Encoding": "identity"},
                        extensions={"sni_hostname": url.raw_host.decode("ascii")},
                    ) as response:
                        if response.is_redirect and (location := response.headers.get("location")):
                            url = url.join(location)
                            continue
                        if response.status_code in (401, 403, 404, 410):
                            raise InvalidDocument("source_inaccessible")
                        response.raise_for_status()
                        mime = response.headers.get("content-type", "").split(";", 1)[0].lower()
                        metadata = Message()
                        metadata["Content-Disposition"] = response.headers.get("content-disposition", "")
                        path = metadata.get_filename() or unquote(url.path)
                        name = PurePosixPath(path.replace("\\", "/")).name.replace("\x00", "").strip()
                        extension = PurePosixPath(name).suffix.lower().removeprefix(".")
                        format = CONTENT_FORMATS.get(mime, extension)
                        if mime in ("text/html", "application/xhtml+xml") or format not in DOCUMENT_FORMATS:
                            raise InvalidDocument("unsupported_source_format")
                        if response.headers.get("content-encoding", "identity").lower() != "identity":
                            raise InvalidDocument("unsupported_source_encoding")
                        return await read_document(response), format, name or url.host
    except (OSError, TimeoutError, httpx.HTTPError, httpx.InvalidURL) as error:
        raise RagUnavailable("source_unavailable") from error
    raise InvalidDocument("too_many_redirects")
