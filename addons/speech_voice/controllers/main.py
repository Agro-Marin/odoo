import base64
import binascii
import time
from collections import defaultdict, deque

from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import request

from odoo.addons.speech_voice.tools.utterance import (
    can_hear_commands,
    transcribe_utterance,
)

MAX_COMMANDS_PER_MINUTE = 30

# per process: a burst from one user holds HTTP threads, and one worker's
# count is enough to stop that burst
_recent_commands: defaultdict[int, deque[float]] = defaultdict(deque)


def _throttle(uid: int) -> None:
    now = time.monotonic()
    recent = _recent_commands[uid]
    while recent and now - recent[0] > 60:
        recent.popleft()
    if len(recent) >= MAX_COMMANDS_PER_MINUTE:
        raise UserError(request.env._("Too many voice commands; wait a moment."))
    recent.append(now)


class SpeechVoiceController(http.Controller):
    def _check_internal(self) -> None:
        if not request.env.user._is_internal():
            raise AccessError(request.env._("Voice commands are for internal users."))

    @http.route("/speech_voice/available", type="jsonrpc", auth="user")
    def available(self) -> dict:
        return {
            "available": request.env.user._is_internal()
            and can_hear_commands(request.env)
        }

    @http.route("/speech_voice/transcribe", type="jsonrpc", auth="user")
    def transcribe(
        self, audio: str, language: str | None = None, prompt: str | None = None
    ) -> dict:
        self._check_internal()
        _throttle(request.env.uid)
        try:
            data = base64.b64decode(audio, validate=True)
        except (binascii.Error, ValueError) as error:
            raise UserError(request.env._("The recording is not readable.")) from error
        return {"text": transcribe_utterance(request.env, data, language, prompt)}
