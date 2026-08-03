import enum
import ipaddress
import logging
import re
import socket
import time
from urllib.parse import urljoin, urlsplit

import chardet
import requests
from lxml import html
from urllib3.exceptions import LocationParseError

_logger = logging.getLogger(__name__)

# Open Graph / <title> metadata lives in <head>; never buffer more than this
# while scanning for </head> (guards against unbounded streamed responses).
MAX_HEAD_BYTES = 512 * 1024
# Cap redirect chains we follow ourselves (see _fetch_link_preview_response).
MAX_REDIRECTS = 5
# Total wall-clock budget for one preview (all redirect hops plus the body scan).
# requests' ``timeout=3`` is a per-read *inactivity* timeout, so a host dribbling
# bytes (a slowloris) would otherwise hold a request worker indefinitely.
MAX_FETCH_SECONDS = 10


class UrlSafety(enum.Enum):
    """Outcome of resolving and classifying a URL's host.

    Callers deciding only "may I fetch this?" collapse everything but SAFE to
    "no" (see :func:`_url_is_safe`). Callers that also decide whether the target
    is *permanently* bad (web push deletes the subscription) must not confuse
    BLOCKED with the transient UNRESOLVABLE.
    """

    SAFE = "safe"  # resolved exclusively to public (global) addresses
    BLOCKED = "blocked"  # resolved to a non-global address; never contact it
    UNRESOLVABLE = "unresolvable"  # bad scheme/host, or DNS could not resolve now


def _classify_url_safety(url):
    """Resolve ``url``'s host and classify it (see :class:`UrlSafety`).

    ``url`` is attacker-controlled (message bodies, user-registered push
    endpoints) and fetched server-side as sudo, so without this guard it is an
    SSRF primitive: ``ipaddress.is_global`` is False for exactly the set to
    reject (loopback, private, link-local, reserved, multicast, CGNAT).
    """
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
        # UNRESOLVABLE, not BLOCKED: a resolver blip or a proxy-only egress where
        # getaddrinfo fails is transient, not a permanently bad target.
        return UrlSafety.UNRESOLVABLE
    if not addrinfos:
        return UrlSafety.UNRESOLVABLE
    for *_, sockaddr in addrinfos:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            # A resolved address we cannot even parse: do not contact it, but do
            # not treat it as a permanent target failure either.
            return UrlSafety.UNRESOLVABLE
        if not ip.is_global:
            return UrlSafety.BLOCKED
    # Residual TOCTOU: this classifies at resolution time, so an attacker
    # controlling DNS can still rebind before the socket connect.
    return UrlSafety.SAFE


def _url_is_safe(url):
    """Return True only if ``url`` is an http(s) URL whose host resolves
    exclusively to public IP addresses. Thin bool wrapper over
    :func:`_classify_url_safety` for callers that only gate fetching."""
    return _classify_url_safety(url) is UrlSafety.SAFE


def _fetch_link_preview_response(url, request_session, headers, deadline=None):
    """GET ``url`` for a link preview, following redirects manually so every
    hop is re-validated by :func:`_url_is_safe` (an SSRF-safe host can still
    302 to an internal one). Returns the final ``requests.Response`` (streamed)
    or None if a hop is unsafe, the redirect budget is exhausted, or the overall
    time ``deadline`` (monotonic seconds) is passed."""
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


def get_link_preview_from_url(url, request_session=None):
    """Get the Open Graph properties of an url (https://ogp.me/).

    An url leading directly to an image mimetype is returned as the preview
    image; otherwise the properties come from the html page, streamed since
    they are declared in the <head> tag.

    :param request_session: optional shared session, faster on same-domain urls
    """
    # Some websites are blocking non browser user agent.
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:91.0) Gecko/20100101 Firefox/91.0",
        "Odoo-Link-Preview": "True",  # Used to identify coming from the link previewer
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
    # Close the streamed connection on every exit path: the image branch and
    # get_link_preview_from_html's early break leave sockets dangling otherwise.
    with response:
        if not response.ok or not response.headers.get("Content-Type"):
            return False
        # Content-Type header can return a charset, but we just need the
        # mimetype (eg: image/jpeg;charset=ISO-8859-1)
        content_type = response.headers["Content-Type"].split(";")
        if response.headers["Content-Type"].startswith("image/"):
            return {
                "image_mimetype": content_type[0],
                "og_image": url,  # If the url mimetype is already an image type, set url as preview image
                "source_url": url,
            }
        elif response.headers["Content-Type"].startswith("text/html"):
            return get_link_preview_from_html(url, response, deadline)
        return False


def get_link_preview_from_html(url, response, deadline=None):
    """Retrieve the Open Graph properties from the html page (https://ogp.me/).

    The page is read in 8kb chunks to avoid loading more than the <head> tag,
    and the <title> tag is used when no Open Graph title property is present.
    """
    content = b""
    for chunk in response.iter_content(chunk_size=8192):
        content += chunk
        pos = content.find(b"</head>", -8196 * 2)
        if pos != -1:
            content = content[: pos + 7]
            break
        # requests' timeout is a per-read inactivity timeout, not a size cap: a
        # large body with no </head> would grow `content` without bound.
        if len(content) > MAX_HEAD_BYTES:
            break
        # A slow trickle never trips the per-read timeout, so also stop once the
        # overall wall-clock budget is exhausted (slowloris protection).
        if deadline is not None and time.monotonic() > deadline:
            _logger.info("Link preview timed out (body scan) for: %s", url)
            break

    if not content:
        return False

    # requests defaults a charset-less text/* response to ISO-8859-1 (RFC 2616
    # §3.7.1), which decodes a page declaring utf-8 only via <meta charset> as
    # latin-1 -> mojibake. With no charset in the header, prefer the HTML5
    # default: a successful strict utf-8 decode is decisive, since valid UTF-8
    # bytes essentially never decode cleanly under another charset.
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
            # chardet may return {"encoding": None}; keep an explicit fallback.
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
