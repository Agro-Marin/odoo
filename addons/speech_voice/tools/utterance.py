from __future__ import annotations

from typing import Any

from odoo.exceptions import UserError
from odoo.libs.documents import EXPENSIVE, Document

from odoo.addons.speech.tools.engines import can_transcribe, engine_error

COMMAND_PURPOSE = "speech.transcription.command"
UTTERANCE_MIMETYPE = "audio/wav"
MAX_UTTERANCE_SECONDS = 15
# 16-bit mono at 16 kHz, what the browser's recorder sends, plus the header
MAX_UTTERANCE_BYTES = 16_000 * 2 * MAX_UTTERANCE_SECONDS + 44


def can_hear_commands(env: Any) -> bool:
    return can_transcribe(UTTERANCE_MIMETYPE, env, COMMAND_PURPOSE)


def transcribe_utterance(
    env: Any, audio: bytes, language: str | None = None, prompt: str | None = None
) -> str:
    if not audio:
        return ""
    if len(audio) > MAX_UTTERANCE_BYTES:
        raise UserError(
            env._(
                "A voice command lasts at most %(seconds)s seconds.",
                seconds=MAX_UTTERANCE_SECONDS,
            )
        )
    if not can_hear_commands(env):
        raise UserError(env._("No speech engine may hear voice commands here."))
    document = Document(
        audio,
        UTTERANCE_MIMETYPE,
        "utterance.wav",
        env=env,
        company=env.company,
        read_up_to=EXPENSIVE,
        purpose=COMMAND_PURPOSE,
        language=language or None,
        prompt=prompt or None,
    )
    cues = document.cues or []
    failure = engine_error(document)
    if failure and not cues:
        raise UserError(failure)
    return " ".join(cue.text.strip() for cue in cues if cue.text.strip())
