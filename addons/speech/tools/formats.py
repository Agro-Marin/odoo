from __future__ import annotations

from odoo.libs.documents import (
    CUES,
    Format,
    get_format,
    get_format_of_extension,
    register_format,
)

SPEECH_FORMATS = (
    ("audio/mpeg", "mp3", "MP3 audio", frozenset({"audio/mp3", "audio/x-mpeg"})),
    ("audio/ogg", "ogg", "Ogg audio", frozenset({"audio/opus", "audio/vorbis"})),
    ("audio/wav", "wav", "WAV audio", frozenset({"audio/x-wav", "audio/wave"})),
    ("audio/webm", "weba", "WebM audio", frozenset()),
    ("audio/mp4", "m4a", "MPEG-4 audio", frozenset({"audio/x-m4a"})),
    ("audio/flac", "flac", "FLAC audio", frozenset({"audio/x-flac"})),
    ("audio/aac", "aac", "AAC audio", frozenset()),
    ("video/webm", "webm", "WebM video", frozenset()),
    ("video/mp4", "mp4", "MPEG-4 video", frozenset()),
    ("video/quicktime", "mov", "QuickTime video", frozenset()),
    ("video/x-matroska", "mkv", "Matroska video", frozenset()),
)


def register_speech_formats() -> None:
    for mimetype, extension, label, accepts in SPEECH_FORMATS:
        if get_format(mimetype) or get_format_of_extension(extension):
            continue
        register_format(
            Format(
                mimetype=mimetype,
                extension=extension,
                representation=CUES,
                accepts=accepts,
                label=label,
            )
        )


register_speech_formats()
