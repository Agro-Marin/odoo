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

    # Legacy FontAwesome / odoo_ui_icons character-code mapping for /font_to_img.
    # Maps legacy Twitter codes to their X replacement and lists new icons that
    # require the odoo_ui_icons font instead of FontAwesome.
    _OI_FONT_CHAR_CODES = {
        # Replacement of existing Twitter icons by X icons (the route here
        # receives the old icon code always, but the replacement one is also
        # considered for consistency anyway).
        "61569": "59464",  # F081 -> E848: fa-twitter-square
        "61593": "59418",  # F099 -> E81A: fa-twitter
        # Addition of new icons
        "59407": "59407",  # E80F: fa-strava
        "59409": "59409",  # E811: fa-discord
        "59416": "59416",  # E818: fa-threads
        "59417": "59417",  # E819: fa-kickstarter
        "59419": "59419",  # E81B: fa-tiktok
        "59420": "59420",  # E81C: fa-bluesky
        "59421": "59421",  # E81D: fa-google-play
    }

    @classmethod
    def _redirect_to_generic_fallback(cls, model, res_id, access_token=None, **kwargs):
        if request.session.uid is None:
            return cls._redirect_to_login_with_mail_view(
                model,
                res_id,
                access_token=access_token,
                **kwargs,
            )
        return cls._redirect_to_messaging()

    @classmethod
    def _redirect_to_messaging(cls):
        url = "/odoo/action-mail.action_discuss"
        return request.redirect(url)

    @classmethod
    def _redirect_to_login_with_mail_view(
        cls, model, res_id, access_token=None, **kwargs
    ):
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
    def _check_token(cls, token):
        base_link = request.httprequest.path
        params = dict(request.params)
        params.pop("token", "")
        valid_token = request.env["mail.thread"]._encode_link(base_link, params)
        return consteq(valid_token, str(token))

    @classmethod
    def _check_token_and_record_or_redirect(cls, model, res_id, token):
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
    def _redirect_to_record(cls, model, res_id, access_token=None, **kwargs):
        # access_token and kwargs are used in the portal controller override for the Send by email or Share Link
        # to give access to the record to a recipient that has normally no access.
        uid = request.session.uid
        user = request.env["res.users"].sudo().browse(uid)
        cids = []

        # no model / res_id, meaning no possible record -> redirect to login
        if not model or not res_id or model not in request.env:
            return cls._redirect_to_generic_fallback(
                model,
                res_id,
                access_token=access_token,
                **kwargs,
            )

        # find the access action using sudo to have the details about the access link
        RecordModel = request.env[model]
        record_sudo = RecordModel.sudo().browse(res_id).exists()
        if not record_sudo:
            # record does not seem to exist -> redirect to login
            return cls._redirect_to_generic_fallback(
                model,
                res_id,
                access_token=access_token,
                **kwargs,
            )

        suggested_company = record_sudo._get_redirect_suggested_company()
        # the record has a window redirection: check access rights
        if uid is not None:
            if not RecordModel.with_user(uid).has_access("read"):
                return cls._redirect_to_generic_fallback(
                    model,
                    res_id,
                    access_token=access_token,
                    **kwargs,
                )
            try:
                # We need here to extend the "allowed_company_ids" to allow a redirection
                # to any record that the user can access, regardless of currently visible
                # records based on the "currently allowed companies".
                cids_str = request.cookies.get("cids", str(user.company_id.id))
                try:
                    cids = [int(cid) for cid in cids_str.split("-")]
                except ValueError:
                    # malformed cookie -> fall back to user's main company
                    cids = [user.company_id.id]
                try:
                    record_sudo.with_user(uid).with_context(
                        allowed_company_ids=cids
                    ).check_access("read")
                except AccessError:
                    # In case the allowed_company_ids from the cookies (i.e. the last user configuration
                    # on their browser) is not sufficient to avoid an ir.rule access error, try to following
                    # heuristic:
                    # - Guess the supposed necessary company to access the record via the method
                    #   _get_redirect_suggested_company
                    #   - If no company, then redirect to the messaging
                    #   - Merge the suggested company with the companies on the cookie
                    # - Make a new access test if it succeeds, redirect to the record. Otherwise,
                    #   redirect to the messaging.
                    if not suggested_company:
                        raise AccessError(
                            _(
                                "There is no candidate company that has read access to the record."
                            )
                        ) from None
                    cids = cids + [suggested_company.id]
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
            # we have an act_url (probably a portal link): we need to retry being logged to check access
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
        # the record has an URL redirection: use it directly
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
        # anything else than an act_window is not supported
        elif record_action["type"] != "ir.actions.act_window":
            return cls._redirect_to_messaging()

        # backend act_window: when not logged, unless really readable as public,
        # user is going to be redirected to login -> keep mail/view as redirect
        # in that case. In case of readable record, we consider this might be
        # a customization and we do not change the behavior in stable
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

        # @see commit c63d14a0485a553b74a8457aee158384e9ae6d3f
        # @see router.js: heuristics to discrimate a model name from an action path
        # is the presence of dots, or the prefix m- for models
        model_in_url = model if "." in model else "m-" + model
        url = f"/odoo/{model_in_url}/{res_id}?{urlencode(sorted(url_params.items()))}"
        return request.redirect(url)

    @http.route("/mail/view", type="http", auth="public")
    def mail_action_view(self, model=None, res_id=None, access_token=None, **kwargs):
        """Generic access point from notification emails. The heuristic to
           choose where to redirect the user is the following :

        - find a public URL
        - if none found
         - users with a read access are redirected to the document
         - users without read access are redirected to the Messaging
         - not logged users are redirected to the login page

           models that have an access_token may apply variations on this.
        """
        # ==============================================================================================
        # This block of code disappeared on saas-11.3 to be reintroduced by TBE.
        # This is needed because after a migration from an older version to saas-11.3, the link
        # received by mail with a message_id no longer work.
        # So this block of code is needed to guarantee the backward compatibility of those links.
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
        # ==============================================================================================

        if res_id and isinstance(res_id, str):
            try:
                res_id = int(res_id)
            except ValueError:
                res_id = False
        return self._redirect_to_record(model, res_id, access_token, **kwargs)

    # csrf is disabled here because it will be called by the MUA with unpredictable session at that time
    @http.route("/mail/unfollow", type="http", auth="public", csrf=False)
    def mail_action_unfollow(self, model, res_id, pid, token, **kwargs):
        # auth="public", csrf=False: res_id/pid are fully client-controlled. A
        # non-numeric value used to reach a bare int()/browse() and surface an
        # uncaught ValueError as an HTTP 500 to anonymous callers. Coerce first;
        # a malformed id simply cannot match a valid (record, token) pair.
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
    def mail_thread_message_redirect(self, message_id, **kwargs):
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

    # web_editor routes need to be kept otherwise mail already sent won't be able to load icons anymore
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
        icon,
        color="#000",
        bg=None,
        size=100,
        alpha=255,
        width=None,
        height=None,
    ):
        """This method converts an unicode character to an image (using Font
        Awesome font by default) and is used only for mass mailing because
        custom fonts are not supported in mail.

        :param icon : decimal encoding of unicode character
        :param color : RGB code of the color
        :param bg : RGB code of the background color
        :param size : Pixels in integer
        :param alpha : transparency of the image from 0 to 255
        :param width : Pixels in integer
        :param height : Pixels in integer

        :returns PNG image converted from given font
        """
        # The font is a fixed server-side asset, never caller-controlled: this
        # is an auth="none" route, so exposing `font` as a parameter let an
        # unauthenticated caller point ImageFont.truetype at any file inside the
        # addons tree (file-existence oracle / 500 on a non-font file).
        font = "/web/static/src/libs/fontawesome7/webfonts/fa-solid-900.woff2"
        # For custom icons, use the corresponding custom font
        if icon.isdigit() and icon in self._OI_FONT_CHAR_CODES:
            icon = self._OI_FONT_CHAR_CODES[icon]
            font = "/web/static/lib/odoo_ui_icons/fonts/odoo_ui_icons.woff"

        size = max(width, height, 1) if width else size
        width = width or size
        height = height or size
        # Make sure we have at least size=1
        width = max(1, min(width, 512))
        height = max(1, min(height, 512))
        # Initialize font
        font = font.removeprefix("/")
        font_obj = ImageFont.truetype(file_open(font, "rb"), height)

        # if received character is not a number, keep old behaviour (icon is character)
        if icon.isdigit():
            code = int(icon)
            # chr() only accepts a valid Unicode code point; a huge value on
            # this unauthenticated (auth="none") route would raise ValueError
            # and surface as a 500. Reject out-of-range codes cleanly instead.
            if code > 0x10FFFF:
                raise request.not_found()
            icon = chr(code)

        # Background standardization
        if bg is not None and bg.startswith("rgba"):
            bg = bg.replace("rgba", "rgb")
            bg = ",".join(bg.split(",")[:-1]) + ")"

        # Strip alpha channel from color — icon opacity comes from glyph shape
        if color is not None and color.startswith("rgba"):
            color = color.replace("rgba", "rgb")
            color = ",".join(color.split(",")[:-1]) + ")"

        # Validate the caller-supplied colors up-front: an invalid color string
        # would otherwise raise ValueError deep inside PIL (Image.new / draw.text)
        # and surface as a 500 on this auth="none" route. Reject cleanly with a
        # 404, matching the size/glyph-width hardening above.
        for _color in (color, bg):
            if _color is not None:
                try:
                    ImageColor.getrgb(_color)
                except ValueError:
                    raise request.not_found() from None

        # Measure the icon glyph dimensions
        dummy = Image.new("RGBA", (1, 1))
        draw = ImageDraw.Draw(dummy)
        bbox = draw.textbbox((0, 0), icon, font=font_obj)
        # Clamp the glyph width to the same 512px ceiling as height/width: a long
        # caller-supplied non-digit `icon` string would otherwise size the output
        # image by its full rendered width, an unauthenticated memory amplifier.
        boxw = max(1, min(bbox[2] - bbox[0], 512))

        # Render icon directly on the output image
        outimage = Image.new("RGBA", (boxw, height), bg or (0, 0, 0, 0))
        draw = ImageDraw.Draw(outimage)
        draw.text((0, 0), icon, font=font_obj, fill=color)

        # output image
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
