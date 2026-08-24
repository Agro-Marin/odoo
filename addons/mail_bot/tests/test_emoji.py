import re
from pathlib import Path

from odoo.modules.module import get_module_path
from odoo.tests import tagged

from odoo.addons.mail_bot.models.mail_bot import _EMOJI_BMP_RANGES
from odoo.addons.mail_bot.tests.common import MailBotCommon

# The exact BMP set the module accepted before the table was replaced by a
# regex. Narrowing it is a regression; widening it is a decision.
_HISTORICAL_BMP = frozenset(
    codepoint
    for low, high in _EMOJI_BMP_RANGES
    for codepoint in range(low, high + 1)
)


@tagged("odoobot")
class TestEmojiDetection(MailBotCommon):

    def _picker_emojis(self):
        """Every emoji `web`'s picker can insert."""
        path = get_module_path("web")
        self.assertTrue(path, "web is not installed")
        source = Path(path) / "static/src/components/emoji_picker/emoji_data.js"
        content = source.read_text(encoding="utf-8")
        emojis = [
            found
            for found in re.findall(r'"codepoints":\s*"((?:[^"\\]|\\.)*)"', content)
            if found
        ]
        self.assertGreater(len(emojis), 1000, "emoji_data.js did not parse")
        return emojis

    def test_every_picker_emoji_is_recognised(self):
        """Anything the user can click in Odoo's own picker counts as an emoji.

        The hand-maintained table this replaced stopped at U+1F9FF and rejected
        87 of the 1452 entries -- a user picked 🧊 and was told they had not
        sent an emoji.
        """
        bot = self.env["mail.bot"]
        unrecognised = [
            emoji for emoji in self._picker_emojis() if not bot._body_contains_emoji(emoji)
        ]
        self.assertFalse(
            unrecognised,
            f"{len(unrecognised)} emoji from web's picker are not recognised: "
            f"{' '.join(unrecognised[:30])}",
        )

    def test_emoji_coverage_is_never_narrowed(self):
        """Every codepoint the module has ever accepted is still accepted."""
        bot = self.env["mail.bot"]
        lost = [
            hex(codepoint)
            for codepoint in sorted(_HISTORICAL_BMP)
            if not bot._body_contains_emoji(chr(codepoint))
        ]
        self.assertFalse(lost, f"emoji coverage narrowed: {lost}")

    def test_plain_text_is_not_an_emoji(self):
        bot = self.env["mail.bot"]
        for body in (
            "hello world", "cafés naïve", "日本語のテキスト", "x -> y",
            "price is 100 EUR", "<p>a<b>c</b></p>", "item 1 two", "",
        ):
            self.assertFalse(bot._body_contains_emoji(body), f"{body!r} is not an emoji")

    def test_emoji_is_found_anywhere_in_the_body(self):
        bot = self.env["mail.bot"]
        for body in ("😊", "<p>tagada 😊</p>", "😊 leading", "trailing 😊"):
            self.assertTrue(bot._body_contains_emoji(body), f"{body!r} holds an emoji")
