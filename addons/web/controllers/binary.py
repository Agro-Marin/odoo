import base64
import io
import logging
import unicodedata
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from werkzeug.utils import send_file

import odoo
from odoo import SUPERUSER_ID, _, api, http
from odoo.exceptions import AccessError, UserError
from odoo.http import Response, request
from odoo.libs.filesystem import guess_mimetype
from odoo.tools import file_open, file_path, replace_exceptions, str2bool
from odoo.tools.assets.constants import ANY_UNIQUE
from odoo.tools.image import image_guess_size_from_field_name
from odoo.tools.misc import verify_limited_field_access_token

_logger = logging.getLogger(__name__)

BAD_X_SENDFILE_ERROR = """\
Odoo is running with --x-sendfile but is receiving /web/filestore requests.

With --x-sendfile enabled, NGINX should be serving the
/web/filestore route, however Odoo is receiving the
request.

This usually indicates that NGINX is badly configured,
please make sure the /web/filestore location block exists
in your configuration file and that it is similar to:

    location /web/filestore {{
        internal;
        alias {data_dir}/filestore;
    }}
"""


def clean(name: str) -> str:
    return name.replace("<", "").replace(">", "")


def _int_or_zero(value) -> int:
    try:
        return int(value)
    except TypeError, ValueError:
        return 0


def _res_id_or_none(value) -> int | None:
    if value is None or value is False or value == "":
        return None
    try:
        return int(value)
    except TypeError, ValueError:
        return None


def _token_authorized_public(record, field, access_token) -> bool:
    if not access_token:
        return False
    return bool(
        verify_limited_field_access_token(record, field, access_token, scope="binary")
    )


class Binary(http.Controller):
    @http.route("/web/filestore/<path:_path>", type="http", auth="none")
    def content_filestore(self, _path: str) -> Response:
        if odoo.tools.config["x_sendfile"]:
            _logger.error(
                BAD_X_SENDFILE_ERROR.format(data_dir=odoo.tools.config["data_dir"])
            )
        raise http.request.not_found()

    @http.route(
        [
            "/web/content",
            "/web/content/<string:xmlid>",
            "/web/content/<string:xmlid>/<string:filename>",
            "/web/content/<int:id>",
            "/web/content/<int:id>/<string:filename>",
            "/web/content/<string:model>/<int:id>/<string:field>",
            "/web/content/<string:model>/<int:id>/<string:field>/<string:filename>",
        ],
        type="http",
        auth="public",
        readonly=True,
    )
    def content_common(
        self,
        xmlid: str | None = None,
        model: str = "ir.attachment",
        id: int | str | None = None,
        field: str = "raw",
        filename: str | None = None,
        filename_field: str = "name",
        mimetype: str | None = None,
        unique: str | bool = False,
        download: str | bool = False,
        access_token: str | None = None,
        nocache: str | bool = False,
    ) -> Response:
        with replace_exceptions(UserError, by=request.not_found()):
            record = request.env["ir.binary"]._get_record(
                xmlid, model, _res_id_or_none(id), access_token, field_name=field
            )
            stream = request.env["ir.binary"]._get_stream_from_record(
                record, field, filename, filename_field, mimetype
            )
            if _token_authorized_public(record, field, access_token):
                stream.public = True

        send_file_kwargs = {"as_attachment": str2bool(download, False)}
        if unique:
            send_file_kwargs["immutable"] = True
            send_file_kwargs["max_age"] = http.STATIC_CACHE_LONG
        if str2bool(nocache, False):
            send_file_kwargs["max_age"] = None

        return stream.get_response(**send_file_kwargs)

    @http.route(
        ["/web/assets/scope/<string:scope>/<string:unique>/<string:filename>"],
        type="http",
        auth="public",
        readonly=True,
    )
    def content_assets_scoped(self, scope: str, **kwargs: Any) -> Response:
        if scope not in request.env["ir.asset"]._get_addons_installed():
            raise request.not_found()
        return self.content_assets(**kwargs, assets_params={"unit_test_scope": scope})

    @http.route(
        ["/web/assets/<string:unique>/<string:filename>"],
        type="http",
        auth="public",
        readonly=True,
    )
    def content_assets(
        self,
        filename: str,
        unique: str = ANY_UNIQUE,
        nocache: str | bool = False,
        assets_params: dict[str, Any] | None = None,
    ) -> Response:
        env = request.env
        assets_params = assets_params or {}
        if not isinstance(assets_params, dict):
            raise request.not_found()
        debug_assets = unique == "debug"
        stream = None
        if unique in ("any", "%"):
            unique = ANY_UNIQUE
        if unique != "debug":
            url = env["ir.asset"]._get_asset_bundle_url_pattern(
                filename, unique, assets_params
            )
            if "%" in url:
                raise request.not_found()
            domain = [
                ("public", "=", True),
                ("url", "!=", False),
                ("url", "=like", url),
                ("res_model", "=", "ir.ui.view"),
                ("res_id", "=", 0),
                ("create_uid", "=", SUPERUSER_ID),
            ]
            attachment = env["ir.attachment"].sudo().search(domain, limit=1)
            if attachment:
                stream = env["ir.binary"]._get_stream_from_record(
                    attachment, "raw", filename
                )
        if stream is None:
            if env.cr.readonly:
                env.cr.rollback()
                cursor_manager = env.registry.cursor(readonly=False)
            else:
                cursor_manager = nullcontext(env.cr)
            with cursor_manager as rw_cr:
                rw_env = api.Environment(rw_cr, env.user.id, {})
                try:
                    if filename.endswith(".map"):
                        _logger.error(
                            ".map should have been generated through debug assets, (version %s most likely outdated)",
                            unique,
                        )
                        raise request.not_found()
                    bundle_name, rtl, asset_type, autoprefix = rw_env[
                        "ir.asset"
                    ]._parse_bundle_name(filename, debug_assets)
                    css = asset_type == "css"
                    js = asset_type == "js"
                    bundle = rw_env["ir.qweb"]._get_asset_bundle(
                        bundle_name,
                        css=css,
                        js=js,
                        debug_assets=debug_assets,
                        rtl=rtl,
                        autoprefix=autoprefix,
                        assets_params=assets_params,
                    )
                    if (
                        not debug_assets
                        and unique != ANY_UNIQUE
                        and unique != bundle.get_version(asset_type)
                    ):
                        return request.redirect(bundle.get_link(asset_type))
                    attachment = None
                    if css and bundle.stylesheets:
                        attachment = bundle.css()
                    elif js and (bundle.javascripts or bundle.templates):
                        attachment = bundle.js()
                    if attachment:
                        stream = rw_env["ir.binary"]._get_stream_from_record(
                            attachment, "raw", filename
                        )
                except ValueError as e:
                    _logger.warning(
                        "Parsing asset bundle %s has failed: %s", filename, e
                    )
                    raise request.not_found() from e
        if stream is None:
            raise request.not_found()
        if stream.type == "url":
            stream.type = "data"
            stream.data = b""
            stream.size = 0
            stream.url = None
        send_file_kwargs = {
            "as_attachment": False,
            "content_security_policy": None,
        }
        if str2bool(nocache, False):
            send_file_kwargs["max_age"] = None
        elif unique and unique != "debug":
            send_file_kwargs["immutable"] = True
            send_file_kwargs["max_age"] = http.STATIC_CACHE_LONG

        return stream.get_response(**send_file_kwargs)

    @http.route(
        ["/web/assets/esm/<string:unique>/<string:filename>"],
        type="http",
        auth="public",
        readonly=True,
    )
    def content_esm_assets(self, unique: str, filename: str) -> Response:
        attachment = (
            request.env["ir.attachment"]
            .sudo()
            .search(
                [
                    ("public", "=", True),
                    ("url", "=", f"/web/assets/esm/{unique}/{filename}"),
                    ("res_model", "=", "ir.ui.view"),
                    ("res_id", "=", 0),
                    ("create_uid", "=", SUPERUSER_ID),
                ],
                limit=1,
                order="id desc",
            )
        )
        if not attachment:
            raise request.not_found()
        stream = request.env["ir.binary"]._get_stream_from_record(
            attachment,
            "raw",
            filename,
        )
        return stream.get_response(
            as_attachment=False,
            content_security_policy=None,
            immutable=True,
            max_age=http.STATIC_CACHE_LONG,
        )

    @http.route(
        [
            "/web/image",
            "/web/image/<string:xmlid>",
            "/web/image/<string:xmlid>/<string:filename>",
            "/web/image/<string:xmlid>/<int:width>x<int:height>",
            "/web/image/<string:xmlid>/<int:width>x<int:height>/<string:filename>",
            "/web/image/<string:model>/<int:id>/<string:field>",
            "/web/image/<string:model>/<int:id>/<string:field>/<string:filename>",
            "/web/image/<string:model>/<int:id>/<string:field>/<int:width>x<int:height>",
            "/web/image/<string:model>/<int:id>/<string:field>/<int:width>x<int:height>/<string:filename>",
            "/web/image/<int:id>",
            "/web/image/<int:id>/<string:filename>",
            "/web/image/<int:id>/<int:width>x<int:height>",
            "/web/image/<int:id>/<int:width>x<int:height>/<string:filename>",
            "/web/image/<int:id>-<string:unique>",
            "/web/image/<int:id>-<string:unique>/<string:filename>",
            "/web/image/<int:id>-<string:unique>/<int:width>x<int:height>",
            "/web/image/<int:id>-<string:unique>/<int:width>x<int:height>/<string:filename>",
        ],
        type="http",
        auth="public",
        readonly=True,
        save_session=False,
    )
    def content_image(
        self,
        xmlid: str | None = None,
        model: str = "ir.attachment",
        id: int | str | None = None,
        field: str = "raw",
        filename_field: str = "name",
        filename: str | None = None,
        mimetype: str | None = None,
        unique: str | bool = False,
        download: str | bool = False,
        width: int | str = 0,
        height: int | str = 0,
        crop: str | bool = False,
        access_token: str | None = None,
        nocache: str | bool = False,
    ) -> Response:
        crop = str2bool(crop, False)
        width = _int_or_zero(width)
        height = _int_or_zero(height)
        try:
            record = request.env["ir.binary"]._get_record(
                xmlid, model, _res_id_or_none(id), access_token, field_name=field
            )
            stream = request.env["ir.binary"]._get_stream_image_from_record(
                record,
                field,
                filename=filename,
                filename_field=filename_field,
                mimetype=mimetype,
                width=width,
                height=height,
                crop=crop,
            )
            if _token_authorized_public(record, field, access_token):
                stream.public = True
        except UserError as exc:
            if str2bool(download, False):
                raise request.not_found() from exc
            if (width, height) == (0, 0):
                width, height = image_guess_size_from_field_name(field)
            record = request.env.ref("web.image_placeholder").sudo()
            stream = request.env["ir.binary"]._get_stream_image_from_record(
                record,
                "raw",
                width=width,
                height=height,
                crop=crop,
            )
            stream.public = False

        send_file_kwargs = {"as_attachment": str2bool(download, False)}
        if unique:
            send_file_kwargs["immutable"] = True
            send_file_kwargs["max_age"] = http.STATIC_CACHE_LONG
        if str2bool(nocache, False):
            send_file_kwargs["max_age"] = None

        return stream.get_response(**send_file_kwargs)

    @http.route("/web/binary/upload_attachment", type="http", auth="user")
    def upload_attachment(
        self,
        model: str,
        id: int | str,
        ufile: Any,
    ) -> Response:
        files = request.httprequest.files.getlist("ufile")
        Attachment = request.env["ir.attachment"]
        results = []
        for uploaded_file in files:
            filename = uploaded_file.filename
            if request.httprequest.user_agent.browser == "safari":
                filename = unicodedata.normalize("NFD", uploaded_file.filename)

            try:
                uploaded_file.filename = filename
                attachment = Attachment._create_from_request_file(
                    uploaded_file,
                    res_model=model,
                    res_id=int(id),
                )
                attachment._post_add_create()
            except AccessError:
                results.append(
                    {"error": _("You are not allowed to upload an attachment here.")}
                )
            except Exception:
                results.append({"error": _("Something horrible happened")})
                _logger.exception(
                    "Fail to upload attachment %s", uploaded_file.filename
                )
            else:
                results.append(
                    {
                        "filename": clean(filename),
                        "mimetype": attachment.mimetype,
                        "id": attachment.id,
                        "size": attachment.file_size,
                    }
                )
        return request.make_json_response(results)

    @http.route(
        [
            "/web/binary/company_logo",
            "/logo",
            "/logo.png",
        ],
        type="http",
        auth="none",
        cors="*",
        readonly=True,
    )
    def company_logo(self, **kw: Any) -> Response:
        imgname = "logo"
        imgext = ".png"
        dbname = request.db
        uid = (request.session.uid if dbname else None) or odoo.SUPERUSER_ID

        if not dbname:
            response = http.Stream.from_path(
                file_path("web/static/img/logo.png")
            ).get_response()
        else:
            try:
                try:
                    company = int(kw["company"]) if kw.get("company") else False
                except ValueError, TypeError:
                    company = False
                if company:
                    request.env.cr.execute(
                        """
                        SELECT logo_web, write_date
                          FROM res_company
                         WHERE id = %s
                    """,
                        (company,),
                    )
                else:
                    request.env.cr.execute(
                        """
                        SELECT c.logo_web, c.write_date
                          FROM res_users u
                     LEFT JOIN res_company c
                            ON c.id = u.company_id
                         WHERE u.id = %s
                    """,
                        (uid,),
                    )
                row = request.env.cr.fetchone()
                if row and row[0]:
                    image_base64 = base64.b64decode(row[0])
                    image_data = io.BytesIO(image_base64)
                    mimetype = guess_mimetype(image_base64, default="image/png")
                    imgext = "." + mimetype.split("/")[1]
                    if imgext == ".svg+xml":
                        imgext = ".svg"
                    response = send_file(
                        image_data,
                        request.httprequest.environ,
                        download_name=imgname + imgext,
                        mimetype=mimetype,
                        last_modified=row[1],
                        response_class=Response,
                    )
                else:
                    response = http.Stream.from_path(
                        file_path("web/static/img/nologo.png")
                    ).get_response()
            except Exception:
                _logger.warning(
                    "While retrieving the company logo, using the Odoo logo instead",
                    exc_info=True,
                )
                response = http.Stream.from_path(
                    file_path("web/static/img/logo.png")
                ).get_response()

        return response

    @http.route(
        [
            "/web/sign/get_fonts",
            "/web/sign/get_fonts/<string:fontname>",
        ],
        type="jsonrpc",
        auth="none",
        readonly=True,
    )
    def get_fonts(self, fontname: str | None = None) -> list[bytes]:
        supported_exts = (".ttf", ".otf", ".woff", ".woff2")
        fonts = []
        fonts_dir = Path(file_path("web/static/fonts/sign"))
        if fontname:
            if Path(fontname).name != fontname:
                raise request.not_found()
            with file_open(
                str(fonts_dir / fontname), "rb", filter_ext=supported_exts
            ) as font_file:
                fonts.append(base64.b64encode(font_file.read()))
        else:
            font_filenames = sorted(
                fn.name for fn in fonts_dir.iterdir() if fn.suffix in supported_exts
            )
            for filename in font_filenames:
                with file_open(
                    str(fonts_dir / filename), "rb", filter_ext=supported_exts
                ) as font_file:
                    fonts.append(base64.b64encode(font_file.read()))
        return fonts
