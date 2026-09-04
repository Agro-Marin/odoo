from __future__ import annotations

from typing import Any

from odoo.libs.documents import ANY, CUES, TEXT, get_readers, get_writers

AUDIO_MIMETYPES = frozenset(
    {
        "audio/aac",
        "audio/flac",
        "audio/mp4",
        "audio/mpeg",
        "audio/ogg",
        "audio/opus",
        "audio/wav",
        "audio/webm",
        "audio/x-m4a",
        "audio/x-wav",
    }
)

VIDEO_MIMETYPES = frozenset(
    {
        "video/mp4",
        "video/mpeg",
        "video/ogg",
        "video/quicktime",
        "video/webm",
        "video/x-matroska",
    }
)

SPOKEN_MIMETYPES = AUDIO_MIMETYPES | VIDEO_MIMETYPES

DEFAULT_SPEECH_MIMETYPE = "audio/mpeg"


def bare(mimetype: str) -> str:
    return (mimetype or "").split(";")[0].strip().lower()


def is_spoken(mimetype: str) -> bool:
    return bare(mimetype) in SPOKEN_MIMETYPES


def _is_usable(engine: Any, env: Any) -> bool:
    declared = getattr(engine, "available", None)
    return True if declared is None else bool(declared(env))


def transcription_engines(mimetype: str, env: Any = None) -> tuple[Any, ...]:
    return tuple(
        reader
        for reader in get_readers(bare(mimetype), CUES)
        if ANY not in reader.mimetypes and (env is None or _is_usable(reader, env))
    )


def synthesis_engines(mimetype: str, env: Any = None) -> tuple[Any, ...]:
    return tuple(
        writer
        for writer in get_writers(bare(mimetype), TEXT)
        if writer.mimetype != ANY and (env is None or _is_usable(writer, env))
    )


def can_transcribe(mimetype: str, env: Any = None) -> bool:
    return is_spoken(mimetype) and bool(transcription_engines(mimetype, env))


def can_synthesize(mimetype: str = DEFAULT_SPEECH_MIMETYPE, env: Any = None) -> bool:
    return bool(synthesis_engines(mimetype, env))


ENGINE_ERROR = "speech_engine_error"


def record_engine_error(document: Any, error: BaseException) -> None:
    document.options[ENGINE_ERROR] = str(error) or type(error).__name__


def engine_error(document: Any) -> str:
    return document.options.get(ENGINE_ERROR) or ""
