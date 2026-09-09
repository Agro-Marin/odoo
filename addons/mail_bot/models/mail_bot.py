import random
import re
from collections.abc import Callable
from typing import Any, NamedTuple

from markupsafe import Markup

from odoo import models
from odoo.tools import html2plaintext

ODOOBOT_XMLID = "base.partner_root"

# sequence forms -- arrows, double-bang, copyright, keycap digits -- that no
_EMOJI_BMP_RANGES = (
    (0x231A, 0x231B),
    (0x2328, 0x2328),
    (0x23CF, 0x23CF),
    (0x23E9, 0x23F3),
    (0x23F8, 0x23FA),
    (0x24C2, 0x24C2),
    (0x25AA, 0x25AB),
    (0x25B6, 0x25B6),
    (0x25C0, 0x25C0),
    (0x25FB, 0x25FE),
    (0x2600, 0x2604),
    (0x260E, 0x260E),
    (0x2611, 0x2611),
    (0x2614, 0x2615),
    (0x2618, 0x2618),
    (0x261D, 0x261D),
    (0x2620, 0x2620),
    (0x2622, 0x2623),
    (0x2626, 0x2626),
    (0x262A, 0x262A),
    (0x262E, 0x262F),
    (0x2638, 0x263A),
    (0x2640, 0x2640),
    (0x2642, 0x2642),
    (0x2648, 0x2653),
    (0x265F, 0x2660),
    (0x2663, 0x2663),
    (0x2665, 0x2666),
    (0x2668, 0x2668),
    (0x267B, 0x267B),
    (0x267E, 0x267F),
    (0x2692, 0x2697),
    (0x2699, 0x2699),
    (0x269B, 0x269C),
    (0x26A0, 0x26A1),
    (0x26AA, 0x26AB),
    (0x26B0, 0x26B1),
    (0x26BD, 0x26BE),
    (0x26C4, 0x26C5),
    (0x26C8, 0x26C8),
    (0x26CE, 0x26CF),
    (0x26D1, 0x26D1),
    (0x26D3, 0x26D4),
    (0x26E9, 0x26EA),
    (0x26F0, 0x26FA),
    (0x26FD, 0x26FD),
    (0x2702, 0x2702),
    (0x2705, 0x2705),
    (0x2708, 0x270D),
    (0x270F, 0x270F),
    (0x2712, 0x2712),
    (0x2714, 0x2714),
    (0x2716, 0x2716),
    (0x271D, 0x271D),
    (0x2721, 0x2721),
    (0x2728, 0x2728),
    (0x2733, 0x2734),
    (0x2744, 0x2744),
    (0x2747, 0x2747),
    (0x274C, 0x274C),
    (0x274E, 0x274E),
    (0x2753, 0x2755),
    (0x2757, 0x2757),
    (0x2763, 0x2764),
    (0x2795, 0x2797),
    (0x27A1, 0x27A1),
    (0x27B0, 0x27B0),
    (0x27BF, 0x27BF),
    (0x2934, 0x2935),
    (0x2B05, 0x2B07),
    (0x2B1B, 0x2B1C),
    (0x2B50, 0x2B50),
    (0x2B55, 0x2B55),
    (0x3030, 0x3030),
    (0x303D, 0x303D),
    (0x3297, 0x3297),
    (0x3299, 0x3299),
)
_EMOJI_RE = re.compile(
    "["
    + "".join(
        chr(low) if low == high else f"{chr(low)}-{chr(high)}"
        for low, high in _EMOJI_BMP_RANGES
    )
    + "\U0001f000-\U0001faff"
    + "️⃣"
    + "]"
)

_STYLE = {
    "new_line": Markup("<br>"),
    "bold_start": Markup("<b>"),
    "bold_end": Markup("</b>"),
    "command_start": Markup("<span class='o_odoobot_command'>"),
    "command_end": Markup("</span>"),
    "document_link_start": Markup(
        "<a href='https://www.odoo.com/documentation' target='_blank'>"
    ),
    "document_link_end": Markup("</a>"),
    "slides_link_start": Markup(
        "<a href='https://www.odoo.com/slides' target='_blank'>"
    ),
    "slides_link_end": Markup("</a>"),
    "paperclip_icon": Markup("<i class='fa-solid fa-paperclip' aria-hidden='true'/>"),
}


class _Step(NamedTuple):
    state: str
    next_state: str
    trigger: Callable[..., bool]
    success: Callable[..., Any]
    retry: Callable[..., Any]


_ONBOARDING_STEPS = (
    _Step(
        state="onboarding_emoji",
        next_state="onboarding_command",
        trigger=lambda self, body, values, command: self._body_contains_emoji(body),
        success=lambda self: self.env._(
            "Great! 👍%(new_line)sTo access special commands, %(bold_start)sstart your "
            "sentence with%(bold_end)s %(command_start)s/%(command_end)s. Try getting "
            "help.",
            **_STYLE,
        ),
        retry=lambda self: self.env._(
            "Not exactly. To continue the tour, send an emoji:"
            " %(bold_start)stype%(bold_end)s%(command_start)s :)%(command_end)s and "
            "press enter.",
            **_STYLE,
        ),
    ),
    _Step(
        state="onboarding_command",
        next_state="onboarding_ping",
        trigger=lambda self, body, values, command: command == "help",
        success=lambda self: self.env._(
            "Wow you are a natural!%(new_line)sPing someone with @username to grab their "
            "attention. %(bold_start)sTry to ping me using%(bold_end)s "
            "%(command_start)s@OdooBot%(command_end)s in a sentence.",
            **_STYLE,
        ),
        retry=lambda self: self.env._(
            "Not sure what you are doing. Please, type "
            "%(command_start)s/%(command_end)s and wait for the propositions."
            " Select %(command_start)shelp%(command_end)s and press enter.",
            **_STYLE,
        ),
    ),
    _Step(
        state="onboarding_ping",
        next_state="onboarding_attachment",
        trigger=lambda self, body, values, command: (
            self._get_odoobot().id in (values.get("partner_ids") or [])
        ),
        success=lambda self: self.env._(
            "Yep, I am here! 🎉 %(new_line)sNow, try %(bold_start)ssending an "
            "attachment%(bold_end)s, like a picture of your cute dog...",
            **_STYLE,
        ),
        retry=lambda self: self.env._(
            "Sorry, I am not listening. To get someone's attention, %(bold_start)sping "
            "him%(bold_end)s. Write %(command_start)s@OdooBot%(command_end)s and select"
            " me.",
            **_STYLE,
        ),
    ),
    _Step(
        state="onboarding_attachment",
        next_state="onboarding_canned",
        trigger=lambda self, body, values, command: bool(values.get("attachment_ids")),
        success=lambda self: self._begin_canned_response_step(),
        retry=lambda self: self.env._(
            "To %(bold_start)ssend an attachment%(bold_end)s, click on the "
            "%(paperclip_icon)s icon and select a file.",
            **_STYLE,
        ),
    ),
    _Step(
        state="onboarding_canned",
        next_state="idle",
        trigger=lambda self, body, values, command: bool(
            self.env.context.get("canned_response_ids")
        ),
        success=lambda self: self._finish_canned_response_step(),
        retry=lambda self: self.env._(
            "Not sure what you are doing. Please, type %(command_start)s:%(command_end)s "
            "and wait for the propositions. Select one of them and press enter.",
            **_STYLE,
        ),
    ),
)

_STEPS_BY_STATE = {step.state: step for step in _ONBOARDING_STEPS}

_RESTARTABLE_STATES = (False, "idle", "not_initialized")


class MailBot(models.AbstractModel):
    _name = "mail.bot"
    _description = "Mail Bot"

    def _get_odoobot(self):
        return self.env.ref(ODOOBOT_XMLID)

    def _apply_logic(self, channel, values, command=None):
        channel.check_singleton()
        odoobot = self._get_odoobot()
        if values.get("author_id") == odoobot.id or (
            values.get("message_type") != "comment" and not command
        ):
            return
        answer = self._get_answer(channel, values, command)
        if not answer:
            return
        for one_answer in answer if isinstance(answer, list) else [answer]:
            channel.sudo().message_post(
                author_id=odoobot.id,
                body=one_answer,
                message_type="comment",
                silent=True,
                subtype_xmlid="mail.mt_comment",
            )

    @staticmethod
    def _normalise_body(body):
        return (
            html2plaintext(body or "").replace("\xa0", " ").strip().lower().strip(".!")
        )

    def _get_answer(self, channel, values, command=False):
        if channel.channel_type != "chat":
            return False
        odoobot = self._get_odoobot()
        if odoobot not in channel.channel_member_ids.partner_id:
            return False

        user = self.env.user
        odoobot_state = user.odoobot_state
        if odoobot_state == "disabled":
            return False

        body = self._normalise_body(values.get("body"))
        step = _STEPS_BY_STATE.get(odoobot_state)
        if step and step.trigger(self, body, values, command):
            return self._advance_to(step.next_state, step.success)

        if odoobot_state == "idle" and body in [
            "❤️",
            self.env._("i love you"),
            self.env._("love"),
        ]:
            return self.env._(
                "Aaaaaw that's really cute but, you know, bots don't work that way. "
                "You're too human for me! Let's keep it professional ❤️"
            )
        if self.env._("fuck") in body or "fuck" in body:
            return self.env._("That's not nice! I'm a bot but I have feelings... 💔")
        if (
            odoobot_state in _RESTARTABLE_STATES
            and self.env._("start the tour") in body
        ):
            user.sudo().odoobot_state = "onboarding_emoji"
            return self.env._("To start, try to send me an emoji :)")
        if self._is_help_requested(body) or odoobot_state == "idle":
            return self._documentation_answer()
        if step:
            answer = step.retry(self)
            if user.odoobot_failed:
                answer += _STYLE["new_line"] + self._documentation_answer()
            else:
                user.sudo().odoobot_failed = True
            return answer
        return random.choice(
            [
                self.env._(
                    "I'm not smart enough to answer your question.%(new_line)sTo follow my "
                    "guide, ask: %(command_start)sstart the tour%(command_end)s.",
                    **_STYLE,
                ),
                self.env._("Hmmm..."),
                self.env._("I'm afraid I don't understand. Sorry!"),
                self.env._(
                    "Sorry I'm sleepy. Or not! Maybe I'm just trying to hide my unawareness"
                    " of human language...%(new_line)sI can show you features if you write:"
                    " %(command_start)sstart the tour%(command_end)s.",
                    **_STYLE,
                ),
            ]
        )

    def _advance_to(self, next_state, success):
        answer = success(self)
        self.env.user.sudo().write(
            {"odoobot_state": next_state, "odoobot_failed": False}
        )
        return answer

    def _begin_canned_response_step(self):
        user = self.env.user
        canned_response = self.env["mail.canned.response"].create(
            {
                "source": self.env._("Thanks"),
                "substitution": self.env._("Thanks for your feedback. Goodbye!"),
            }
        )
        user.sudo().odoobot_canned_response_id = canned_response
        return self.env._(
            "Wonderful! 😇%(new_line)sTry typing %(command_start)s::%(command_end)s to use "
            "canned responses. I've created a temporary one for you.",
            **_STYLE,
        )

    def _finish_canned_response_step(self):
        user = self.env.user
        user.sudo().odoobot_canned_response_id.sudo().unlink()
        return [
            self.env._(
                "Great! You can customize %(bold_start)scanned responses%(bold_end)s in the Discuss app.",
                **_STYLE,
            ),
            self.env._(
                "That’s the end of this overview. You can %(bold_start)sclose this conversation%(bold_end)s or type "
                "%(command_start)sstart the tour%(command_end)s to see it again. Enjoy exploring Odoo!",
                **_STYLE,
            ),
        ]

    def _documentation_answer(self):
        return self.env._(
            "Unfortunately, I'm just a bot 😞 I don't understand! If you need help "
            "discovering our product, please check %(document_link_start)sour "
            "documentation%(document_link_end)s or %(slides_link_start)sour "
            "videos%(slides_link_end)s.",
            **_STYLE,
        )

    def _body_contains_emoji(self, body):
        return bool(_EMOJI_RE.search(body))

    def _is_help_requested(self, body):
        return "?" in body or any(
            re.search(rf"\b{re.escape(token)}\b", body)
            for token in ("help", self.env._("help"))
        )
