"""Safe URL joining utilities."""

import re
import urllib.parse

__all__ = ["urljoin"]


_MAX_UNQUOTE_PASSES = 4


def _segment_core(segment: str) -> str:
    r"""Reduce a path segment to what a lenient server may resolve it to.

    A ``..`` traversal can hide behind trailing bytes that the origin server
    strips *after* this check but *before* resolving dot segments:

    - a path-parameter (``..;foo`` -> ``..``): RFC 3986 ``;`` params are not part
      of the directory name, and Tomcat/Spring drop them before normalisation
      (the well-known ``..;/`` bypass);
    - a NUL or control byte (``..%00foo`` -> ``..``): C-string based servers
      truncate at the NUL, and control characters are not legal in a URL path
      unencoded, so anything from the first one on is attacker padding.

    Checking the *reduced* core, not the raw segment, closes both without
    touching legitimate segments (``v1.2;beta`` -> ``v1.2``, ``..foo`` -> ``..foo``).
    """
    segment = segment.split(";", 1)[0]
    for i, ch in enumerate(segment):
        if ch < "\x20" or ch == "\x7f":
            return segment[:i]
    return segment


def _contains_dot_segments(path: str) -> bool:
    r"""Return whether ``path`` resolves to a dot segment under any decoding.

    Most servers decode the url before resolving dot segments, and a proxy in
    front of another decoder can decode more than once -- so ``%252e%252e``
    reaches the origin as ``..``.  Decoding a single time missed that.
    Backslash counts as a separator here because browsers (and several servers)
    normalize ``\\`` to ``/``, which made ``a\\..\\..\\etc`` slip through a
    check that only split on ``/``.  Each segment is further reduced by
    :func:`_segment_core` so ``..`` cannot hide behind a ``;`` path-parameter or
    a NUL/control-byte truncation.

    ``errors="replace"``: a valid percent-encoding of a non-UTF-8 byte (e.g.
    ``%ff``) must not raise UnicodeDecodeError here -- this is a predicate on a
    caller-supplied URL, not a validator, and its callers (website domain
    constraints, urljoin) treat a raise as a crash rather than a rejection.
    Substituting U+FFFD is safe for the traversal check because "." and ".."
    are pure ASCII, so a replaced byte can never manufacture a dot segment; it
    also cannot mask one, since the bytes that would form it decode unchanged.
    """
    current = path
    for _ in range(_MAX_UNQUOTE_PASSES):
        if any(
            _segment_core(seg) in (".", "..")
            for seg in current.replace("\\", "/").split("/")
        ):
            return True
        decoded = urllib.parse.unquote(current, errors="replace")
        if decoded == current:
            return False
        current = decoded
    return True


def urljoin(base: str, extra: str) -> str:
    """Join a trusted base URL with a relative URL safely.

    Unlike standard URL joins that follow RFC 3986 (e.g., `urllib.parse.urljoin`),
    this function enforces strict behavior that better aligns with developer
    expectations and guards against path traversals, unplanned redirects, and
    accidental host/scheme overrides.

    - Behaves similarly to `base + '/' + extra`
    - Keeps scheme and netloc from `base`, and raises an error if `extra` has them
    - Ignores any scheme/host in `extra`
    - Forbids `.` and `..` path traversal, including through repeated
      percent-decoding (`%252e%252e`) and backslash separators
    - Joins the paths; the query and fragment are taken from `extra` only --
      any query or fragment on `base` is dropped

    :param base: Trusted base URL or path.
    :param extra: Relative URL (`path`, `?query`, `#frag`). No scheme & host allowed unless it matches `base`
    :returns: joined URL.
    :raises TypeError: If inputs are not strings.
    :raises ValueError: `extra` contains dot-segments or is an absolute URL.

    Examples::

        >>> urljoin('https://api.example.com/v1/?bar=fiz', '/users/42?bar=bob')
        'https://api.example.com/v1/users/42?bar=bob'

        >>> urljoin('https://example.com/foo', 'http://8.8.8.8/foo')
        Traceback (most recent call last):
            ...
        ValueError: Extra URL must use same scheme and host as base, and begin with base path

        >>> urljoin('https://api.example.com/data/', '/?lang=fr')
        'https://api.example.com/data/?lang=fr'
    """
    if not isinstance(base, str):
        msg = "Base URL must be a string"
        raise TypeError(msg)
    if not isinstance(extra, str):
        msg = "Extra URL must be a string"
        raise TypeError(msg)

    b_scheme, b_netloc, path, _, _ = urllib.parse.urlsplit(base)
    e_scheme, e_netloc, e_path, e_query, e_fragment = urllib.parse.urlsplit(extra)

    if e_scheme or e_netloc:
        if (
            (e_scheme != b_scheme)
            or (e_netloc != b_netloc)
            or not e_path.startswith(path)
        ):
            msg = "Extra URL must use same scheme and host as base, and begin with base path"
            raise ValueError(msg)

        e_path = e_path.removeprefix(path)

    if e_path:
        e_path = e_path.lstrip(
            "/\\\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\x0c\r\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f "
        )
        path = f"{path}/{e_path}"

    path = re.sub(r"/+", "/", path)

    if _contains_dot_segments(path):
        msg = "Dot segments are not allowed"
        raise ValueError(msg)

    return urllib.parse.urlunsplit((b_scheme, b_netloc, path, e_query, e_fragment))
