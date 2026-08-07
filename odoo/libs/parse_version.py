__all__ = ["parse_version"]

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

component_re = re.compile(r"(\d+ | [a-z]+ | \.| -)", re.VERBOSE)
replace = {
    "pre": "c",
    "preview": "c",
    "-": "final-",
    "_": "final-",
    "rc": "c",
    "dev": "@",
    "saas": "",
    "~": "",
}.get


def _parse_version_parts(s: str) -> Iterator[str]:
    for part in component_re.split(s):
        part = replace(part, part)
        if not part or part == ".":
            continue
        if part[:1] in "0123456789":
            yield part.zfill(8)
        else:
            yield "*" + part

    yield "*final"


def parse_version(s: str) -> tuple[str, ...]:
    parts: list[str] = []
    for part in _parse_version_parts((s or "0.1").lower()):
        if part.startswith("*"):
            if part < "*final":
                while parts and parts[-1] == "*final-":
                    parts.pop()
            while parts and parts[-1] == "00000000":
                parts.pop()
        parts.append(part)
    return tuple(parts)
