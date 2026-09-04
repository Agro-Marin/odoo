from __future__ import annotations

from typing import Any

from odoo.libs.documents import ANY, CUES, EXPENSIVE, TEXT, get_readers, get_writers

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


def is_spoken(mimetype: str) -> bool:
    return (mimetype or "").split(";")[0].strip().lower() in SPOKEN_MIMETYPES


def _is_usable(engine: Any, env: Any) -> bool:
    # An engine is registered by installing its module and usable only once a
    # credential for it exists, and the two are not the same question: without
    # this the UI offers a button that fails at the vendor call.
    declared = getattr(engine, "available", None)
    return True if declared is None else bool(declared(env))


def transcription_engines(mimetype: str, env: Any = None) -> tuple[Any, ...]:
    return tuple(
        reader
        for reader in get_readers(mimetype, CUES)
        if reader.cost >= EXPENSIVE
        and ANY not in reader.mimetypes
        and (env is None or _is_usable(reader, env))
    )


def synthesis_engines(mimetype: str, env: Any = None) -> tuple[Any, ...]:
    return tuple(
        writer
        for writer in get_writers(mimetype, TEXT)
        if writer.mimetype != ANY and (env is None or _is_usable(writer, env))
    )


def can_transcribe(mimetype: str, env: Any = None) -> bool:
    return is_spoken(mimetype) and bool(transcription_engines(mimetype, env))


def can_synthesize(mimetype: str = DEFAULT_SPEECH_MIMETYPE, env: Any = None) -> bool:
    return bool(synthesis_engines(mimetype, env))


ENGINE_ERROR = "speech_engine_error"


def record_engine_error(document: Any, error: BaseException) -> None:
    # The document layer treats a raising reader as one that had nothing to
    # say, so that a cheaper reader failing cannot lose a dearer one's answer.
    # For a paid, network-bound engine that would make an outage
    # indistinguishable from silence, so the reason is left on the options the
    # caller already holds.
    document.options[ENGINE_ERROR] = str(error) or type(error).__name__


def engine_error(document: Any) -> str:
    return document.options.get(ENGINE_ERROR) or ""
