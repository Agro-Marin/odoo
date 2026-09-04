from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

__all__ = [
    "Cue",
    "cues_as_text",
    "parse_srt",
    "parse_vtt",
    "write_srt",
    "write_vtt",
]

_STAMP = r"(?:(\d+):)?([0-5]?\d):([0-5]\d)[.,](\d{1,3})"
_ARROW = re.compile(rf"^\s*{_STAMP}\s*-->\s*{_STAMP}\s*(?:\s.*)?$")
_VOICE = re.compile(r"^<v(?:\.\S+)*\s+([^>]*)>(.*)$", re.DOTALL)
_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_NOTE = re.compile(r"^(?:NOTE|STYLE|REGION)\b")


@dataclass(frozen=True, slots=True)
class Cue:
    """A span of a recording, and what is said in it."""

    start: float
    end: float
    text: str
    speaker: str = ""


def _seconds(hours: str | None, minutes: str, secs: str, fraction: str) -> float:
    return (
        int(hours or 0) * 3600
        + int(minutes) * 60
        + int(secs)
        + int(fraction.ljust(3, "0")) / 1000
    )


def _stamp(value: float, separator: str) -> str:
    value = max(value, 0.0)
    milliseconds = round(value * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{milliseconds:03d}"


def _blocks(text: str) -> Iterator[list[str]]:
    block: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.strip():
            block.append(line)
        elif block:
            yield block
            block = []
    if block:
        yield block


def _speaker_of(text: str) -> tuple[str, str]:
    match = _VOICE.match(text)
    if not match:
        return "", text
    return match.group(1).strip(), match.group(2)


def _plain(text: str) -> str:
    return _TAG.sub("", text).strip()


def _parse(text: str) -> list[Cue]:
    cues: list[Cue] = []
    for block in _blocks(text):
        if _NOTE.match(block[0]):
            continue
        for index, line in enumerate(block):
            match = _ARROW.match(line)
            if not match:
                continue
            start = _seconds(*match.group(1, 2, 3, 4))
            end = _seconds(*match.group(5, 6, 7, 8))
            body = "\n".join(block[index + 1 :])
            speaker, spoken = _speaker_of(body)
            spoken = _plain(spoken)
            if spoken:
                cues.append(Cue(start, end, spoken, speaker))
            break
    return cues


def parse_vtt(text: str) -> list[Cue]:
    return _parse(text)


def parse_srt(text: str) -> list[Cue]:
    return _parse(text)


def _voiced(cue: Cue) -> str:
    return f"<v {cue.speaker}>{cue.text}" if cue.speaker else cue.text


def _named(cue: Cue) -> str:
    return f"{cue.speaker}: {cue.text}" if cue.speaker else cue.text


def write_vtt(cues: Iterable[Cue]) -> str:
    blocks = [
        f"{_stamp(cue.start, '.')} --> {_stamp(cue.end, '.')}\n{_voiced(cue)}"
        for cue in cues
    ]
    return "WEBVTT\n\n" + "\n\n".join(blocks) + "\n"


def write_srt(cues: Iterable[Cue]) -> str:
    blocks = [
        f"{number}\n{_stamp(cue.start, ',')} --> {_stamp(cue.end, ',')}\n{_named(cue)}"
        for number, cue in enumerate(cues, start=1)
    ]
    return "\n\n".join(blocks) + "\n"


def cues_as_text(cues: Iterable[Cue]) -> str:
    return "\n".join(cue.text for cue in cues if cue.text)
