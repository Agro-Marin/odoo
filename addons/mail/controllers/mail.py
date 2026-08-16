import io
import logging
from urllib.parse import parse_qsl, urlencode, urlparse

from PIL import Image, ImageColor, ImageDraw, ImageFont
from werkzeug.exceptions import NotFound
from werkzeug.utils import send_file

from odoo import _, http
from odoo.exceptions import AccessError
from odoo.http import STATIC_CACHE, Response, request
from odoo.tools import consteq
from odoo.tools.misc import file_open

from odoo.addons.mail.tools.discuss import add_guest_to_context

_logger = logging.getLogger(__name__)


class MailController(http.Controller):
    _cp_path = "/mail"

    _OI_FONT_CHAR_CODES = {
        "61569": "59464",
        "61593": "59418",
        "59407": "59407",
        "59409": "59409",
        "59416": "59416",
        "59417": "59417",
        "59419": "59419",
        "59420": "59420",
        "59421": "59421",
    }

    @classmethod
    def _redirect_to_generic_fallback(
        cls,
        model: str | None,
        res_id: int,
        access_token: str | None = None,
        **kwargs,
    ) -> Response:
        if request.session.uid is None:
            return cls._redirect_to_login_with_mail_view(
                model,
                res_id,
                access_token=access_token,
                **kwargs,
            )
        return cls._redirect_to_messaging()

    @classmethod
    def _redirect_to_messaging(cls) -> Response:
        url = "/odoo/action-mail.action_discuss"
        return request.redirect(url)

    @classmethod
    def _redirect_to_login_with_mail_view(
        cls,
        model: str | None,
        res_id: int,
        access_token: str | None = None,
        **kwargs,
    ) -> Response:
        url_base = "/mail/view"
        url_params = request.env["mail.thread"]._get_action_link_params(
            "view",
            **{
                "model": model,
                "res_id": res_id,
                "access_token": access_token,
                **kwargs,
            },
        )
        mail_view_url = f"{url_base}?{urlencode(sorted(url_params.items()))}"
        return request.redirect(f"/web/login?{urlencode({'redirect': mail_view_url})}")

    @classmethod
    def _check_token(cls, token: str) -> bool:
        base_link = request.httprequest.path
        params = dict(request.params)
        params.pop("token", "")
        valid_token = request.env["mail.thread"]._encode_link(base_link, params)
        return consteq(valid_token, str(token))

    @classmethod
    def _check_token_and_record_or_redirect(
        cls, model: str, res_id: int, token: str
    ) -> tuple:
        comparison = cls._check_token(token)
        if not comparison:
            _logger.warning("Invalid token in route %s", request.httprequest.url)
            return comparison, None, cls._redirect_to_generic_fallback(model, res_id)
        try:
            record = request.env[model].browse(res_id).exists()
        except Exception:
            record = None
            redirect = cls._redirect_to_generic_fallback(model, res_id)
        else:
            redirect = cls._redirect_to_record(model, res_id)
        return comparison, record, redirect

    @classmethod
    def _redirect_to_record(
        cls,
        model: str | None,
        res_id: int,
        access_token: str | None = None,
        **kwargs,
    ) -> Response:
        uid = request.session.uid
        user = request.env["res.users"].sudo().browse(uid)
        cids = []

        if not model or not res_id or model not in request.env:
            return cls._redirect_to_generic_fallback(
                model,
                res_id,
                access_token=access_token,
                **kwargs,
            )

        RecordModel = request.env[model]
        record_sudo = RecordModel.sudo().browse(res_id).exists()
        if not record_sudo:
            return cls._redirect_to_generic_fallback(
                model,
                res_id,
                access_token=access_token,
                **kwargs,
            )

        suggested_company = record_sudo._get_redirect_suggested_company()
        if uid is not None:
            if not RecordModel.with_user(uid).has_access("read"):
                return cls._redirect_to_generic_fallback(
                    model,
                    res_id,
                    access_token=access_token,
                    **kwargs,
                )
            try:
                cids_str = request.cookies.get("cids", str(user.company_id.id))
                try:
                    cids = [int(cid) for cid in cids_str.split("-")]
                except ValueError:
                    cids = [user.company_id.id]
                try:
                    record_sudo.with_user(uid).with_context(
                        allowed_company_ids=cids
                    ).check_access("read")
                except AccessError:
                    if not suggested_company:
                        raise AccessError(
                            _(
                                "There is no candidate company that has read access to the record."
                            )
                        ) from None
                    cids += [suggested_company.id]
                    record_sudo.with_user(uid).with_context(
                        allowed_company_ids=cids
                    ).check_access("read")
                    request.future_response.set_cookie(
                        "cids", "-".join([str(cid) for cid in cids])
                    )
            except AccessError:
                return cls._redirect_to_generic_fallback(
                    model,
                    res_id,
                    access_token=access_token,
                    **kwargs,
                )
            else:
                record_action = record_sudo._get_access_action(access_uid=uid)
        else:
            record_action = record_sudo._get_access_action()
            if (
                record_action["type"] == "ir.actions.act_url"
                and record_action.get("target_type") != "public"
            ):
                return cls._redirect_to_login_with_mail_view(
                    model,
                    res_id,
                    access_token=access_token,
                    **kwargs,
                )

        record_action.pop("target_type", None)
        if record_action["type"] == "ir.actions.act_url":
            url = record_action["url"]
            if highlight_message_id := kwargs.get("highlight_message_id"):
                parsed_url = urlparse(url)
                url = parsed_url._replace(
                    query=urlencode(
                        parse_qsl(parsed_url.query)
                        + [("highlight_message_id", highlight_message_id)]
                    )
                ).geturl()
            return request.redirect(url)
        elif record_action["type"] != "ir.actions.act_window":
            return cls._redirect_to_messaging()

        if uid is None or request.env.user._is_public():
            has_access = record_sudo.with_user(request.env.user).has_access("read")
            if not has_access:
                return cls._redirect_to_login_with_mail_view(
                    model,
                    res_id,
                    access_token=access_token,
                    **kwargs,
                )

        url_params = {}
        menu_id = request.env["ir.ui.menu"]._get_best_backend_root_menu_id_for_model(
            model
        )
        if menu_id:
            url_params["menu_id"] = menu_id
        view_id = record_sudo.get_formview_id()
        if view_id:
            url_params["view_id"] = view_id
        if highlight_message_id := kwargs.get("highlight_message_id"):
            url_params["highlight_message_id"] = highlight_message_id
        if cids:
            request.future_response.set_cookie(
                "cids", "-".join([str(cid) for cid in cids])
            )

        model_in_url = model if "." in model else "m-" + model
        url = f"/odoo/{model_in_url}/{res_id}?{urlencode(sorted(url_params.items()))}"
        return request.redirect(url)

    @http.route("/mail/view", type="http", auth="public")
    def mail_action_view(
        self,
        model: str | None = None,
        res_id: int | str | None = None,
        access_token: str | None = None,
        **kwargs,
    ) -> Response:
        if kwargs.get("message_id"):
            try:
                message = (
                    request.env["mail.message"]
                    .sudo()
                    .browse(int(kwargs["message_id"]))
                    .exists()
                )
            except Exception:
                message = request.env["mail.message"]
            if message:
                model, res_id = message.model, message.res_id

        if res_id and isinstance(res_id, str):
            try:
                res_id = int(res_id)
            except ValueError:
                res_id = False
        return self._redirect_to_record(model, res_id, access_token, **kwargs)

    @http.route("/mail/unfollow", type="http", auth="public", csrf=False)
    def mail_action_unfollow(
        self, model: str, res_id: str, pid: str, token: str, **kwargs
    ) -> Response:
        try:
            res_id, pid = int(res_id), int(pid)
        except TypeError, ValueError:
            raise NotFound from None
        comparison, record, __ = MailController._check_token_and_record_or_redirect(
            model, res_id, token
        )
        if not comparison or not record:
            raise AccessError(_("Non existing record or wrong token."))

        record_sudo = record.sudo()
        record_sudo.message_unsubscribe([pid])

        display_link = True
        if request.session.uid:
            display_link = record.has_access("read")

        return request.render(
            "mail.message_document_unfollowed",
            {
                "name": record_sudo.display_name,
                "model_name": request.env["ir.model"].sudo()._get(model).display_name,
                "access_url": record._notify_get_action_link(
                    "view", model=model, res_id=res_id
                )
                if display_link
                else False,
            },
        )

    @http.route("/mail/message/<int:message_id>", type="http", auth="public")
    @add_guest_to_context
    def mail_thread_message_redirect(self, message_id: int, **kwargs) -> Response:
        message = request.env["mail.message"].search([("id", "=", message_id)])
        if not message:
            if request.env.user._is_public():
                return request.redirect(
                    f"/web/login?redirect=/mail/message/{message_id}"
                )
            raise NotFound

        return self._redirect_to_record(
            message.model, message.res_id, highlight_message_id=message_id
        )

    @http.route(
        [
            "/web_editor/font_to_img/<icon>",
            "/web_editor/font_to_img/<icon>/<color>",
            "/web_editor/font_to_img/<icon>/<color>/<int:size>",
            "/web_editor/font_to_img/<icon>/<color>/<int:width>x<int:height>",
            "/web_editor/font_to_img/<icon>/<color>/<int:size>/<int:alpha>",
            "/web_editor/font_to_img/<icon>/<color>/<int:width>x<int:height>/<int:alpha>",
            "/web_editor/font_to_img/<icon>/<color>/<bg>",
            "/web_editor/font_to_img/<icon>/<color>/<bg>/<int:size>",
            "/web_editor/font_to_img/<icon>/<color>/<bg>/<int:width>x<int:height>",
            "/web_editor/font_to_img/<icon>/<color>/<bg>/<int:width>x<int:height>/<int:alpha>",
            "/mail/font_to_img/<icon>",
            "/mail/font_to_img/<icon>/<color>",
            "/mail/font_to_img/<icon>/<color>/<int:size>",
            "/mail/font_to_img/<icon>/<color>/<int:width>x<int:height>",
            "/mail/font_to_img/<icon>/<color>/<int:size>/<int:alpha>",
            "/mail/font_to_img/<icon>/<color>/<int:width>x<int:height>/<int:alpha>",
            "/mail/font_to_img/<icon>/<color>/<bg>",
            "/mail/font_to_img/<icon>/<color>/<bg>/<int:size>",
            "/mail/font_to_img/<icon>/<color>/<bg>/<int:width>x<int:height>",
            "/mail/font_to_img/<icon>/<color>/<bg>/<int:width>x<int:height>/<int:alpha>",
        ],
        type="http",
        auth="none",
    )
    def export_icon_to_png(
        self,
        icon: str,
        color: str = "#000",
        bg: str | None = None,
        size: int = 100,
        alpha: int = 255,
        width: int | None = None,
        height: int | None = None,
    ) -> Response:
        font = "/web/static/src/libs/fontawesome7/webfonts/fa-solid-900.woff2"
        if icon.isdigit() and icon in self._OI_FONT_CHAR_CODES:
            icon = self._OI_FONT_CHAR_CODES[icon]
            font = "/web/static/lib/odoo_ui_icons/fonts/odoo_ui_icons.woff"

        size = max(width, height, 1) if width else size
        width = width or size
        height = height or size
        width = max(1, min(width, 512))
        height = max(1, min(height, 512))
        font = font.removeprefix("/")
        font_obj = ImageFont.truetype(file_open(font, "rb"), height)

        if icon.isdigit():
            code = int(icon)
            if code > 0x10FFFF:
                raise request.not_found()
            icon = chr(code)

        if bg is not None and bg.startswith("rgba"):
            bg = bg.replace("rgba", "rgb")
            bg = ",".join(bg.split(",")[:-1]) + ")"

        if color is not None and color.startswith("rgba"):
            color = color.replace("rgba", "rgb")
            color = ",".join(color.split(",")[:-1]) + ")"

        for _color in (color, bg):
            if _color is not None:
                try:
                    ImageColor.getrgb(_color)
                except ValueError:
                    raise request.not_found() from None

        dummy = Image.new("RGBA", (1, 1))
        draw = ImageDraw.Draw(dummy)
        bbox = draw.textbbox((0, 0), icon, font=font_obj)
        boxw = max(1, min(bbox[2] - bbox[0], 512))

        outimage = Image.new("RGBA", (boxw, height), bg or (0, 0, 0, 0))
        draw = ImageDraw.Draw(outimage)
        draw.text((0, 0), icon, font=font_obj, fill=color)

        output = io.BytesIO()
        outimage.save(output, format="PNG")
        output.seek(0)
        response = send_file(
            output,
            request.httprequest.environ,
            mimetype="image/png",
            conditional=False,
            etag=False,
            max_age=STATIC_CACHE,
            response_class=Response,
        )
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST"
        return response
