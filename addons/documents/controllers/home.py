from http import HTTPStatus
from typing import Any
from urllib.parse import quote, urlencode

from odoo.http import request, route
from odoo.tools.urls import keep_query

from .documents import ShareRoute
from odoo.addons.web.controllers import home as web_home
from odoo.addons.web.controllers.utils import ensure_db


class Home(web_home.Home):

    def _web_client_readonly(self, rule: Any, args: Any) -> bool:
        path = request.httprequest.path
        if (
            path.startswith("/odoo/documents")
            and (
                request.httprequest.args.get("access_token")
                or path.removeprefix("/odoo/documents/")
            )
            and request.session.uid
        ):
            return False
        return super()._web_client_readonly(rule, args)

    @route(readonly=_web_client_readonly)
    def web_client(self, s_action: str | None = None, **kw: Any) -> Any:
        subpath = kw.get("subpath", "")
        access_token = request.params.get("access_token") or subpath.removeprefix(
            "documents/"
        )
        if (
            not subpath.startswith("documents")
            or not access_token
            or "/" in access_token
        ):
            return super().web_client(s_action, **kw)

        ensure_db()
        request.update_env(user=request.session.uid)
        request.env["ir.http"]._authenticate_explicit("public")

        if not request.env.user._is_internal():
            return request.redirect(
                f"/documents/{quote(access_token, safe='')}?{keep_query('*')}",
                HTTPStatus.TEMPORARY_REDIRECT,
            )

        document_sudo = ShareRoute._from_access_token(
            access_token, follow_shortcut=False
        )

        if not document_sudo:
            Redirect = request.env["documents.redirect"].sudo()
            if document_sudo := Redirect._get_redirection(access_token):
                return request.redirect(
                    f"/odoo/documents/{quote(document_sudo.access_token, safe='')}?{keep_query('*')}",
                    HTTPStatus.MOVED_PERMANENTLY,
                )

        query = {}
        if request.session.debug:
            query["debug"] = request.session.debug
        fragment = {
            "action": request.env.ref("documents.document_action_preference").id,
            "menu_id": request.env.ref("documents.menu_root").id,
            "model": "documents.document",
        }
        if document_sudo:
            fragment.update(
                {
                    f"documents_init_{key}": value
                    for key, value in ShareRoute._documents_get_init_data(
                        document_sudo, request.env.user
                    ).items()
                }
            )
            if "documents_init_open_preview" in kw:
                fragment["documents_init_open_preview"] = kw[
                    "documents_init_open_preview"
                ]
        return request.redirect(f"/web?{urlencode(query)}#{urlencode(fragment)}")
