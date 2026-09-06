from http import HTTPStatus
from typing import Any
from urllib.parse import quote, urlencode

from odoo.http import request, route
from odoo.tools.urls import keep_query

from .document import ShareRoute
from odoo.addons.web.controllers import home as web_home
from odoo.addons.web.controllers.utils import ensure_db


class Home(web_home.Home):

    def _web_client_readonly(self, rule: Any, args: Any) -> bool:
        path = request.httprequest.path
        if request.session.uid and self._share_access_token(
            path.removeprefix("/odoo/"), request.httprequest.args
        ):
            return False
        return super()._web_client_readonly(rule, args)

    @staticmethod
    def _share_access_token(subpath: str, params: Any) -> str:
        # `/odoo/documents` alone is the app, not a share link; only what
        # follows `documents/` (or an explicit parameter) is a token.
        if subpath == "documents":
            return params.get("access_token") or ""
        if subpath.startswith("documents/"):
            return params.get("access_token") or subpath.removeprefix("documents/")
        return ""

    @route(readonly=_web_client_readonly)
    def web_client(self, s_action: str | None = None, **kw: Any) -> Any:
        access_token = self._share_access_token(kw.get("subpath", ""), request.params)
        if not access_token or "/" in access_token:
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

        query = {}
        if request.session.debug:
            query["debug"] = request.session.debug
        fragment = {
            "action": request.env.ref("document.document_action_preference").id,
            "menu_id": request.env.ref("document.menu_root").id,
            "model": "document.document",
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
