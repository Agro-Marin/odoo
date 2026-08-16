import typing
from datetime import timedelta

import babel
import requests

from odoo import fields
from odoo.http import Controller, request, route

if typing.TYPE_CHECKING:
    from odoo.addons.mail.models.mail_message import MailMessage

TRANSLATION_DAILY_LIMIT_PARAM = "mail.translation.daily_limit"
TRANSLATION_DAILY_LIMIT_DEFAULT = 1000


class GoogleTranslateController(Controller):
    def _translation_rate_limited(self) -> bool:
        cap = request.env["ir.config_parameter"]._get_int_param(
            TRANSLATION_DAILY_LIMIT_PARAM, TRANSLATION_DAILY_LIMIT_DEFAULT
        )
        if cap <= 0:
            return False
        since = fields.Datetime.now() - timedelta(days=1)
        count = (
            request.env["mail.message.translation"]
            .sudo()
            .search_count(
                [("create_uid", "=", request.env.uid), ("create_date", ">=", since)]
            )
        )
        return count >= cap

    @route("/mail/message/translate", type="jsonrpc", auth="user")
    def translate(self, message_id: int) -> dict:
        message = request.env["mail.message"].search([("id", "=", message_id)])
        if not message:
            raise request.not_found()
        domain = [
            ("message_id", "=", message.id),
            ("target_lang", "=", request.env.user.lang.split("_")[0]),
        ]
        translation = request.env["mail.message.translation"].sudo().search(domain)
        if not translation:
            if self._translation_rate_limited():
                return {
                    "error": request.env._(
                        "Translation rate limit reached, please retry later."
                    )
                }
            try:
                source_lang = self._detect_source_lang(message)
                target_lang = request.env.user.lang.split("_")[0]
                vals = {
                    "body": self._get_translation(
                        str(message.body), source_lang, target_lang
                    ),
                    "message_id": message.id,
                    "source_lang": source_lang,
                    "target_lang": target_lang,
                }
                translation = (
                    request.env["mail.message.translation"].sudo().create(vals)
                )
            except requests.exceptions.HTTPError as err:
                return {"error": err.response.json()["error"]["message"]}
        try:
            lang_name = babel.Locale(translation.source_lang).get_display_name(
                request.env.user.lang
            )
        except babel.UnknownLocaleError:
            lang_name = translation.source_lang
        return {
            "body": translation.body,
            "lang_name": lang_name,
        }

    def _detect_source_lang(self, message: MailMessage) -> str:
        translation = (
            request.env["mail.message.translation"]
            .sudo()
            .search([("message_id", "=", message.id)], limit=1)
        )
        if translation:
            return translation.source_lang
        response = self._post(endpoint="detect", data={"q": str(message.body)})
        return response.json()["data"]["detections"][0][0]["language"]

    def _get_translation(self, body: str, source_lang: str, target_lang: str) -> str:
        response = self._post(
            data={"q": body, "target": target_lang, "source": source_lang}
        )
        return response.json()["data"]["translations"][0]["translatedText"]

    def _post(self, endpoint: str = "", data: dict | None = None) -> requests.Response:
        api_key = (
            request.env["ir.config_parameter"]
            .sudo()
            .get_param("mail.google_translate_api_key")
        )
        url = f"https://translation.googleapis.com/language/translate/v2/{endpoint}?key={api_key}"
        response = requests.post(url, data=data, timeout=3)
        response.raise_for_status()
        return response
