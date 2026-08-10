import re
import urllib.parse

__all__ = ["contains_dot_segments", "urljoin"]


_MAX_UNQUOTE_PASSES = 4


def _segment_core(segment: str) -> str:
    segment = segment.split(";", 1)[0]
    for i, ch in enumerate(segment):
        if ch < "\x20" or ch == "\x7f":
            return segment[:i]
    return segment


def contains_dot_segments(path: str) -> bool:
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

    if contains_dot_segments(path):
        msg = "Dot segments are not allowed"
        raise ValueError(msg)

    return urllib.parse.urlunsplit((b_scheme, b_netloc, path, e_query, e_fragment))
