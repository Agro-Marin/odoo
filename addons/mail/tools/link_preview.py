import ipaddress
import re
import socket
from urllib.parse import urlparse

import chardet
import requests
from lxml import html
from urllib3.exceptions import LocationParseError


def _is_url_private(url):
    """Return True if the URL resolves to a private/reserved IP address.

    Prevents SSRF attacks by blocking requests to internal networks, cloud
    metadata endpoints, and loopback addresses.
    """
    try:
        hostname = urlparse(url).hostname
        if not hostname:
            return True
        for info in socket.getaddrinfo(
            hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM
        ):
            addr = info[4][0]
            if ipaddress.ip_address(addr).is_private:
                return True
    except socket.gaierror, ValueError, OSError:
        return True
    return False


def _is_response_private(response):
    """Check the actual connection IP after DNS resolution to catch
    DNS rebinding attacks where the IP changes between the initial
    check and the actual connection."""
    try:
        sock = response.raw._connection.sock
        if sock is None:
            return False
        peer = sock.getpeername()
        if peer:
            return ipaddress.ip_address(peer[0]).is_private
    except (AttributeError, OSError, ValueError):
        pass
    return False


def get_link_preview_from_url(url, request_session=None):
    """Get the Open Graph properties of a URL (https://ogp.me/).

    If the URL leads directly to an image mimetype, return the URL as
    preview image, else retrieve the properties from the HTML page.

    Uses a streaming request to avoid loading the whole page — OG
    properties are declared in the ``<head>`` tag.

    The request session is optional; using one can improve performance
    when many URLs share the same domain.
    """
    if _is_url_private(url):
        return False

    # Some websites block non-browser user agents.
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:91.0) Gecko/20100101 Firefox/91.0",
        "Odoo-Link-Preview": "True",  # Used to identify coming from the link previewer
    }
    try:
        if request_session:
            response = request_session.get(
                url, timeout=3, headers=headers, allow_redirects=True, stream=True
            )
        else:
            response = requests.get(
                url, timeout=3, headers=headers, allow_redirects=True, stream=True
            )
    except requests.exceptions.RequestException:
        return False
    except LocationParseError:
        return False
    # Re-check the resolved IP to prevent DNS rebinding attacks where
    # the domain resolves to a private IP after the initial validation.
    if _is_response_private(response):
        response.close()
        return False
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
        return get_link_preview_from_html(url, response)
    return False


def get_link_preview_from_html(url, response):
    """
    Retrieve the Open Graph properties from the html page. (https://ogp.me/)
    Load the page with chunks of 8kb to prevent loading the whole
    html when we only need the <head> tag content.
    Fallback on the <title> tag if the html doesn't have
    any Open Graph title property.
    """
    content = b""
    for chunk in response.iter_content(chunk_size=8192):
        content += chunk
        pos = content.find(b"</head>", -8196 * 2)
        # Stop reading once all the <head> data is found
        if pos != -1:
            content = content[: pos + 7]
            break

    if not content:
        return False

    encoding = response.encoding or chardet.detect(content).get("encoding", "utf-8")
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
        # Fallback on the <title> tag if it exists
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
