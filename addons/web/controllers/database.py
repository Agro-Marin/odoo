import datetime
import ipaddress
import logging
import pathlib
import re
import tempfile

from lxml import html
from werkzeug.datastructures import (
    FileStorage,
)

import odoo
import odoo.modules.registry
from odoo import http
from odoo.http import Response, content_disposition, dispatch_rpc, request
from odoo.service import db
from odoo.service.db import DBNAME_PATTERN  # re-exported; used by template renderer too
from odoo.tools.misc import file_open, str2bool
from odoo.tools.translate import _

from odoo.addons.base.models.ir_qweb import render as qweb_render

_logger = logging.getLogger(__name__)


def _is_loopback(addr: str | None) -> bool:
    """Whether *addr* is a loopback address (127.0.0.0/8, ::1, or an
    IPv4-mapped loopback like ``::ffff:127.0.0.1``). Anything unparseable —
    including ``None`` — is treated as non-loopback (fail closed)."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError, TypeError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    return (mapped or ip).is_loopback


class Database(http.Controller):
    def _handle_insecure_password(self, master_pwd: str) -> None:
        """Upgrade the admin password if it is still the insecure default
        'admin' — but ONLY for loopback callers.

        Promoting the master password is a silent, permanent state change:
        the next operation's ``check_super`` then validates against the just-set
        value. Left ungated, a REMOTE request to an exposed database manager
        could adopt an attacker-chosen secret and lock the real admin out of the
        manager (backup = full data exfiltration, drop = destruction). Gating to
        loopback keeps the "auto-secure a fresh install on first use"
        convenience for a local admin while removing the remote-lockout vector;
        a non-loopback caller must instead set ``admin_passwd`` in the config or
        change the password from localhost. Both the promotion and a refusal
        (default password still in place, request from elsewhere) are logged.

        Behind a reverse proxy the client IP is only accurate with
        ``--proxy-mode`` and a trusted proxy; otherwise ``remote_addr`` is the
        proxy's own (possibly loopback) address.
        """
        if not (odoo.tools.config.verify_admin_password("admin") and master_pwd):
            return
        remote_addr = request.httprequest.remote_addr
        if not _is_loopback(remote_addr):
            _logger.warning(
                "Refusing to auto-promote the default master password for a "
                "non-loopback request from %s. Set 'admin_passwd' in the "
                "config, or change the master password from localhost.",
                remote_addr,
            )
            return
        _logger.warning(
            "Auto-promoting the default master password ('admin') to the value "
            "submitted from loopback (%s).",
            remote_addr,
        )
        dispatch_rpc("db", "change_admin_password", ["admin", master_pwd])

    def _render_template(self, **d) -> str:
        d.setdefault("manage", True)
        d["insecure"] = odoo.tools.config.verify_admin_password("admin")
        d["list_db"] = odoo.tools.config["list_db"]
        d["langs"] = odoo.service.db.exp_list_lang()
        d["countries"] = odoo.service.db.exp_list_countries()
        d["pattern"] = DBNAME_PATTERN
        try:
            d["databases"] = http.db_list()
            d["incompatible_databases"] = odoo.service.db.list_db_incompatible(
                d["databases"]
            )
        except odoo.exceptions.AccessDenied:
            d["databases"] = [request.db] if request.db else []

        templates = {}

        with file_open("web/static/src/public/database_manager.qweb.html", "r") as fd:
            templates["database_manager"] = fd.read()
        with file_open(
            "web/static/src/public/database_manager.master_input.qweb.html", "r"
        ) as fd:
            templates["master_input"] = fd.read()
        with file_open(
            "web/static/src/public/database_manager.create_form.qweb.html", "r"
        ) as fd:
            templates["create_form"] = fd.read()

        def load(template_name):
            fromstring = (
                html.document_fromstring
                if template_name == "database_manager"
                else html.fragment_fromstring
            )
            return (fromstring(templates[template_name]), template_name)

        return qweb_render("database_manager", d, load)

    @http.route("/web/database/selector", type="http", auth="none")
    def selector(self, **kw) -> str:
        if request.db:
            request.env.cr.close()
        return self._render_template(manage=False)

    @http.route("/web/database/manager", type="http", auth="none")
    def manager(self, **kw) -> str:
        if request.db:
            request.env.cr.close()
        return self._render_template()

    @http.route(
        "/web/database/create",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def create(
        self, master_pwd: str, name: str, lang: str, password: str, **post
    ) -> str | Response:
        self._handle_insecure_password(master_pwd)
        try:
            if not re.match(DBNAME_PATTERN, name):
                raise ValueError(
                    _(
                        "Houston, we have a database naming issue! Make sure you only use letters, numbers, underscores, hyphens, or dots in the database name, and you'll be golden."
                    )
                )
            # post.get() can return the string "False", which is truthy in Python
            country_code = post.get("country_code") or False
            dispatch_rpc(
                "db",
                "create_database",
                [
                    master_pwd,
                    name,
                    bool(post.get("demo")),
                    lang,
                    password,
                    post["login"],
                    country_code,
                    post["phone"],
                ],
            )
            credential = {
                "login": post["login"],
                "password": password,
                "type": "password",
            }
            with odoo.modules.registry.Registry(name).cursor() as cr:
                env = odoo.api.Environment(cr, None, {})
                request.session.authenticate(env, credential)
                request._save_session(env)
                request.session.db = name
            return request.redirect("/odoo")
        except Exception as e:
            _logger.exception("Database creation error.")
            error = f"Database creation error: {str(e) or repr(e)}"
        return self._render_template(error=error)

    @http.route(
        "/web/database/duplicate",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def duplicate(
        self,
        master_pwd: str,
        name: str,
        new_name: str,
        neutralize_database: bool | str = False,
    ) -> str | Response:
        self._handle_insecure_password(master_pwd)
        try:
            if not re.match(DBNAME_PATTERN, new_name):
                raise ValueError(
                    _(
                        "Houston, we have a database naming issue! Make sure you only use letters, numbers, underscores, hyphens, or dots in the database name, and you'll be golden."
                    )
                )
            dispatch_rpc(
                "db",
                "duplicate_database",
                [master_pwd, name, new_name, str2bool(neutralize_database)],
            )
            if request.db == name:
                request.env.cr.close()  # duplicating a database leads to an unusable cursor
            return request.redirect("/web/database/manager")
        except Exception as e:
            _logger.exception("Database duplication error.")
            error = f"Database duplication error: {str(e) or repr(e)}"
            return self._render_template(error=error)

    @http.route(
        "/web/database/drop",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def drop(self, master_pwd: str, name: str) -> str | Response:
        self._handle_insecure_password(master_pwd)
        try:
            if not dispatch_rpc("db", "drop", [master_pwd, name]):
                raise RuntimeError(f"Database {name!r} was not found")
            if request.session.db == name:
                request.env.cr.close()  # dropping this database killed our cursor
                request.session.logout()
            return request.redirect("/web/database/manager")
        except Exception as e:
            _logger.exception("Database deletion error.")
            error = f"Database deletion error: {str(e) or repr(e)}"
            return self._render_template(error=error)

    @http.route(
        "/web/database/backup",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def backup(
        self,
        master_pwd: str,
        name: str,
        backup_format: str = "zip",
        filestore: bool | str = True,
    ) -> str | Response:
        filestore = str2bool(filestore)
        self._handle_insecure_password(master_pwd)
        try:
            if backup_format not in {"zip", "dump"}:
                raise ValueError(
                    f"Invalid backup format {backup_format!r}; expected 'zip' or 'dump'"
                )
            odoo.service.db.check_super(master_pwd)
            if name not in http.db_list():
                raise ValueError(f"Database {name!r} is not known")
            ts = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"{name}_{ts}.{backup_format}"
            headers = [
                ("Content-Type", "application/octet-stream; charset=binary"),
                ("Content-Disposition", content_disposition(filename)),
            ]
            dump_stream = odoo.service.db.dump_db(name, None, backup_format, filestore)
            return Response(dump_stream, headers=headers, direct_passthrough=True)
        except Exception as e:
            _logger.exception("Database.backup")
            error = f"Database backup error: {str(e) or repr(e)}"
            return self._render_template(error=error)

    @http.route(
        "/web/database/restore",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
        max_content_length=None,
    )
    def restore(
        self,
        master_pwd: str,
        backup_file: FileStorage,
        name: str,
        copy: bool | str = False,
        neutralize_database: bool | str = False,
    ) -> str | Response:
        tmp_path = None
        try:
            # Inside the try so a failure here (e.g. the admin-password upgrade
            # hitting the minimum-length rule) is logged and surfaced as a
            # restore error instead of escaping as an unlogged 500.
            self._handle_insecure_password(master_pwd)
            db.check_super(master_pwd)
            if not re.match(DBNAME_PATTERN, name):
                raise ValueError(
                    _(
                        "Houston, we have a database naming issue! Make sure you only use letters, numbers, underscores, hyphens, or dots in the database name, and you'll be golden."
                    )
                )
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                # Capture the path BEFORE save() so a failed upload is still
                # cleaned up in the finally block: NamedTemporaryFile is created
                # with delete=False, so it is not removed automatically on error.
                tmp_path = pathlib.Path(tmp.name)
                backup_file.save(tmp)
            db.restore_db(
                name,
                str(tmp_path),
                str2bool(copy),
                str2bool(neutralize_database),
            )
            return request.redirect("/web/database/manager")
        except Exception as e:
            _logger.exception("Database restore error.")
            error = f"Database restore error: {str(e) or repr(e)}"
            return self._render_template(error=error)
        finally:
            if tmp_path:
                tmp_path.unlink(missing_ok=True)

    @http.route(
        "/web/database/change_password",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def change_password(self, master_pwd: str, master_pwd_new: str) -> str | Response:
        try:
            dispatch_rpc("db", "change_admin_password", [master_pwd, master_pwd_new])
            return request.redirect("/web/database/manager")
        except Exception as e:
            error = f"Master password update error: {str(e) or repr(e)}"
            return self._render_template(error=error)

    @http.route("/web/database/list", type="jsonrpc", auth="none")
    # Stringified return annotation: the method name ``list`` shadows the
    # builtin in the class scope where PEP 649 evaluates ``__annotate__``,
    # so an unquoted ``list[str]`` resolves to the method and raises
    # ``TypeError: 'function' object is not subscriptable`` on Python 3.14.
    def list(self) -> list[str]:
        """List available databases; used by the Mobile app.

        :return: list of database names
        :rtype: list[str]
        """
        return http.db_list()
