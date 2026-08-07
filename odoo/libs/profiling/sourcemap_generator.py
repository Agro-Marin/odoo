__all__ = ["SourceMapGenerator", "base64vlq_encode"]

import json
from functools import lru_cache
from typing import Final, NamedTuple


class _Mapping(NamedTuple):
    generated_line: int
    original_line: int
    source: str | None


class SourceMapGenerator:
    def __init__(self, source_root: str | None = None) -> None:
        self.file: str | None = None
        self._source_root: str | None = source_root
        self._sources: dict[str, int] = {}
        self._mappings: list[_Mapping] = []
        self._sources_contents: dict[str, str] = {}
        self._cache: dict[tuple[int, int], str] = {}

    def _serialize_mappings(self) -> str:
        previous_generated_line = 1
        previous_original_line = 0
        previous_source = 0
        encoded_column = base64vlq_encode(0)
        parts: list[str] = []

        for generated_line, original_line, source in self._mappings:
            if generated_line != previous_generated_line:
                parts.append(";" * (generated_line - previous_generated_line))
                previous_generated_line = generated_line

            if source is None:
                continue

            source_idx = self._sources[source]
            source_delta = source_idx - previous_source
            previous_source = source_idx

            line_delta = original_line - 1 - previous_original_line
            previous_original_line = original_line - 1

            cache_key = (source_delta, line_delta)
            if cache_key not in self._cache:
                self._cache[cache_key] = (
                    encoded_column
                    + base64vlq_encode(source_delta)
                    + base64vlq_encode(line_delta)
                    + encoded_column
                )

            parts.append(self._cache[cache_key])

        return "".join(parts)

    def to_json(self) -> dict[str, object]:
        result: dict[str, object] = {
            "version": 3,
            "sources": list(self._sources),
            "mappings": self._serialize_mappings(),
            "sourcesContent": [
                self._sources_contents[source] for source in self._sources
            ],
        }
        if self.file:
            result["file"] = self.file
        if self._source_root:
            result["sourceRoot"] = self._source_root
        return result

    def get_content(self) -> bytes:
        return b")]}'\n" + json.dumps(self.to_json()).encode("utf-8")

    def add_source(
        self,
        source_name: str,
        source_content: str,
        last_index: int,
        start_offset: int = 0,
    ) -> None:
        source_line_count = source_content.count("\n") + 1

        self._sources.setdefault(source_name, len(self._sources))
        self._sources_contents[source_name] = source_content

        append = self._mappings.append
        if start_offset > 0:
            append(_Mapping(last_index + 1, 1, source_name))

        for i in range(1, source_line_count + 1):
            append(_Mapping(last_index + i + start_offset, i, source_name))


B64CHARS: Final = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
SHIFTSIZE: Final[int] = 5
FLAG: Final[int] = 1 << SHIFTSIZE
MASK: Final[int] = FLAG - 1


@lru_cache(maxsize=64)
def base64vlq_encode(*values: int) -> str:
    results: list[int] = []
    add = results.append
    for v in values:
        v = (abs(v) << 1) | int(v < 0)
        while True:
            toencode, v = v & MASK, v >> SHIFTSIZE
            add(toencode | (v and FLAG))
            if not v:
                break
    return bytes(map(B64CHARS.__getitem__, results)).decode()
