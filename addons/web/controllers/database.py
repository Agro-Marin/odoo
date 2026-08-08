import datetime
import ipaddress
import logging
import os
import pathlib
import re
import tempfile

from lxml import html
from markupsafe import Markup
from werkzeug.datastructures import (
    FileStorage,
)

import odoo
import odoo.modules.registry
from odoo import http
from odoo.exceptions import UserError
from odoo.http import Response, content_disposition, dispatch_rpc, request
from odoo.service import db
from odoo.service.db import DBNAME_PATTERN
from odoo.tools.misc import file_open, str2bool
from odoo.tools.translate import _

from odoo.addons.base.models.ir_qweb import render as qweb_render

_logger = logging.getLogger(__name__)

#: Failures that mean "the request was rejected", not "the server broke".  Every
#: one of them is already rendered back to the caller by ``_render_template``,
#: so a stack trace at ERROR adds nothing an operator can act on while making a
#: log look like it holds a fault: posting an unknown backup format to
#: ``/web/database/backup`` — which ``test_backup_invalid_format_rejected`` does
#: on purpose — printed a full traceback under ``ERROR``.
REJECTED_INPUT_ERRORS = (ValueError, odoo.exceptions.AccessDenied)


def _log_operation_failure(operation: str, exc: BaseException) -> None:
    """Log a database-manager failure at the level its cause deserves."""
    if isinstance(exc, REJECTED_INPUT_ERRORS):
        _logger.warning("%s: %s", operation, exc)
    else:
        _logger.exception(operation)


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


DATABASE_MANAGER_TEMPLATES = {
    "database_manager": "web/static/src/public/database_manager.qweb.html",
    "master_input": "web/static/src/public/database_manager.master_input.qweb.html",
    "create_form": "web/static/src/public/database_manager.create_form.qweb.html",
}


def render_database_manager(values: dict) -> Markup:
    """Render the database manager page from *values*.

    Free of ``request`` so that the templates — which the page's JS addresses by
    id — can be rendered, and asserted on, for any combination of values.
    """
    templates = {}
    for name, path in DATABASE_MANAGER_TEMPLATES.items():
        with file_open(path, "r") as fd:
            templates[name] = fd.read()

    def load(template_name):
        fromstring = (
            html.document_fromstring
            if template_name == "database_manager"
            else html.fragment_fromstring
        )
        return (fromstring(templates[template_name]), template_name)

    # a doctype written in the template is dropped by the lxml round-trip, and
    # without one the page renders in quirks mode: <body> stretches to the
    # viewport, document.scrollingElement becomes <body>, and Bootstrap is
    # unsupported there
    return Markup("<!DOCTYPE html>\n") + qweb_render("database_manager", values, load)


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

        return render_database_manager(d)

    @http.route("/web/database/selector", type="http", auth="none")
    def selector(self, **kw) -> str:
        if request.db:
            request.detach_database()
        return self._render_template(manage=False)

    @http.route("/web/database/manager", type="http", auth="none")
    def manager(self, **kw) -> str:
        if request.db:
            request.detach_database()
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
            _log_operation_failure("Database creation error.", e)
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
                request.detach_database()
            return request.redirect("/web/database/manager")
        except Exception as e:
            _log_operation_failure("Database duplication error.", e)
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
                request.detach_database()
                request.session.logout()
            return request.redirect("/web/database/manager")
        except Exception as e:
            _log_operation_failure("Database deletion error.", e)
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
            if backup_format not in odoo.service.db.BACKUP_FORMATS:
                expected = ", ".join(
                    repr(f) for f in sorted(odoo.service.db.BACKUP_FORMATS)
                )
                raise ValueError(
                    f"Invalid backup format {backup_format!r}; expected {expected}"
                )
            odoo.service.db.check_super(master_pwd)
            if name not in http.db_list():
                raise ValueError(f"Database {name!r} is not known")
            ts = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"{name}_{ts}.{backup_format}"
            dump_stream = odoo.service.db.dump_db(name, None, backup_format, filestore)
            # Announce the length.  ``dump_db`` hands back a seekable temp file
            # already fully written, so measuring it is free — and without a
            # Content-Length the body is delimited by nothing but the
            # connection closing.  A transfer cut short mid-download (flaky
            # link, proxy giving up on a multi-GB response) then lands in the
            # browser as a *successful* download of a truncated archive, which
            # only surfaces later as an unrestorable backup.  Declaring the
            # size turns that silent corruption into a visible short read, and
            # lets clients show real progress.
            dump_size = dump_stream.seek(0, os.SEEK_END)
            dump_stream.seek(0)
            headers = [
                ("Content-Type", "application/octet-stream; charset=binary"),
                ("Content-Disposition", content_disposition(filename)),
                ("Content-Length", str(dump_size)),
            ]
            return Response(dump_stream, headers=headers, direct_passthrough=True)
        except Exception as e:
            _log_operation_failure("Database.backup", e)
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
            self._handle_insecure_password(master_pwd)
            db.check_super(master_pwd)
            if not re.match(DBNAME_PATTERN, name):
                raise ValueError(
                    _(
                        "Houston, we have a database naming issue! Make sure you only use letters, numbers, underscores, hyphens, or dots in the database name, and you'll be golden."
                    )
                )
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
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
            _log_operation_failure("Database restore error.", e)
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
            if odoo.tools.config.verify_admin_password("admin"):
                remote_addr = request.httprequest.remote_addr
                if not _is_loopback(remote_addr):
                    _logger.warning(
                        "Refusing a non-loopback master-password change from %s "
                        "while the default password is still in place.",
                        remote_addr,
                    )
                    raise UserError(
                        _(
                            "For security, the master password can only be changed "
                            "from localhost while it is still the default. Set "
                            "'admin_passwd' in the configuration file instead."
                        )
                    )
            dispatch_rpc("db", "change_admin_password", [master_pwd, master_pwd_new])
            return request.redirect("/web/database/manager")
        except Exception as e:
            error = f"Master password update error: {str(e) or repr(e)}"
            return self._render_template(error=error)

    @http.route("/web/database/list", type="jsonrpc", auth="none")
    def list(self) -> list[str]:
        """List available databases; used by the Mobile app.

        :return: list of database names
        :rtype: list[str]
        """
        return http.db_list()
