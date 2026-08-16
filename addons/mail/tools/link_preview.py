import enum
import ipaddress
import logging
import re
import socket
import time
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit

import chardet
import requests
from lxml import html
from urllib3.exceptions import LocationParseError

_logger = logging.getLogger(__name__)

MAX_HEAD_BYTES = 512 * 1024
MAX_REDIRECTS = 5
MAX_FETCH_SECONDS = 10


class UrlSafety(enum.Enum):
    SAFE = "safe"
    BLOCKED = "blocked"
    UNRESOLVABLE = "unresolvable"


def _classify_url_safety(url: str) -> UrlSafety:
    split = urlsplit(url)
    if split.scheme not in ("http", "https"):
        return UrlSafety.UNRESOLVABLE
    try:
        host = split.hostname
        port = split.port or (443 if split.scheme == "https" else 80)
    except ValueError:
        return UrlSafety.UNRESOLVABLE
    if not host:
        return UrlSafety.UNRESOLVABLE
    try:
        addrinfos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror, UnicodeError, ValueError:
        return UrlSafety.UNRESOLVABLE
    if not addrinfos:
        return UrlSafety.UNRESOLVABLE
    for *_, sockaddr in addrinfos:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            return UrlSafety.UNRESOLVABLE
        if not ip.is_global:
            return UrlSafety.BLOCKED
    return UrlSafety.SAFE


def _url_is_safe(url: str) -> bool:
    return _classify_url_safety(url) is UrlSafety.SAFE


def _fetch_link_preview_response(
    url: str,
    request_session: requests.Session | None,
    headers: dict[str, str],
    deadline: float | None = None,
) -> requests.Response | None:
    getter = request_session or requests
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        if deadline is not None and time.monotonic() > deadline:
            _logger.info("Link preview timed out (redirect chain) for: %s", url)
            return None
        if not _url_is_safe(current):
            _logger.info("Link preview blocked for non-public URL: %s", current)
            return None
        response = getter.get(
            current, timeout=3, headers=headers, allow_redirects=False, stream=True
        )
        if response.is_redirect:
            location = response.headers.get("location")
            response.close()
            if not location:
                return None
            current = urljoin(current, location)
            continue
        return response
    return None


def get_link_preview_from_url(
    url: str, request_session: requests.Session | None = None
) -> dict[str, Any] | Literal[False]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:91.0) Gecko/20100101 Firefox/91.0",
        "Odoo-Link-Preview": "True",
    }
    deadline = time.monotonic() + MAX_FETCH_SECONDS
    try:
        response = _fetch_link_preview_response(url, request_session, headers, deadline)
    except requests.exceptions.RequestException:
        return False
    except LocationParseError:
        return False
    if response is None:
        return False
    with response:
        if not response.ok or not response.headers.get("Content-Type"):
            return False
        content_type = response.headers["Content-Type"].split(";")
        if response.headers["Content-Type"].startswith("image/"):
            return {
                "image_mimetype": content_type[0],
                "og_image": url,
                "source_url": url,
            }
        elif response.headers["Content-Type"].startswith("text/html"):
            return get_link_preview_from_html(url, response, deadline)
        return False


def get_link_preview_from_html(
    url: str, response: requests.Response, deadline: float | None = None
) -> dict[str, Any] | Literal[False]:
    content = b""
    for chunk in response.iter_content(chunk_size=8192):
        content += chunk
        pos = content.find(b"</head>", -8196 * 2)
        if pos != -1:
            content = content[: pos + 7]
            break
        if len(content) > MAX_HEAD_BYTES:
            break
        if deadline is not None and time.monotonic() > deadline:
            _logger.info("Link preview timed out (body scan) for: %s", url)
            break

    if not content:
        return False

    header_declared_charset = (
        "charset=" in response.headers.get("Content-Type", "").lower()
    )
    if header_declared_charset:
        encoding = response.encoding
    else:
        try:
            content.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            encoding = (
                response.encoding or chardet.detect(content).get("encoding") or "utf-8"
            )
    try:
        decoded_content = content.decode(encoding)
    except UnicodeDecodeError, TypeError:
        decoded_content = content.decode("utf-8", errors="ignore")

    try:
        tree = html.fromstring(decoded_content)
    except ValueError:
        decoded_content = re.sub(
            r"^<\?xml[^>]+\?>\s*", "", decoded_content, flags=re.IGNORECASE
        )
        tree = html.fromstring(decoded_content)

    og_title = tree.xpath('//meta[@property="og:title"]/@content')
    if og_title:
        og_title = og_title[0]
    elif tree.find(".//title") is not None:
        og_title = tree.find(".//title").text
    else:
        return False
    og_description = tree.xpath('//meta[@property="og:description"]/@content')
    og_type = tree.xpath('//meta[@property="og:type"]/@content')
    og_site_name = tree.xpath('//meta[@property="og:site_name"]/@content')
    og_image = tree.xpath('//meta[@property="og:image"]/@content')
    og_mimetype = tree.xpath('//meta[@property="og:image:type"]/@content')
    return {
        "og_description": og_description[0] if og_description else None,
        "og_image": og_image[0] if og_image else None,
        "og_mimetype": og_mimetype[0] if og_mimetype else None,
        "og_title": og_title,
        "og_type": og_type[0] if og_type else None,
        "og_site_name": og_site_name[0] if og_site_name else None,
        "source_url": url,
    }
