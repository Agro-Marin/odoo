import collections
import datetime
import enum
import logging
import poplib
import typing
from socket import gaierror
from ssl import SSLCertVerificationError, SSLError
from typing import Any, Literal, Self

from odoo import _, api, fields, models
from odoo.api import ValuesType
from odoo.exceptions import UserError
from odoo.fields import Domain

from ..tools.incoming_mail import (
    ENCRYPTION_SELECTION,
    MAILBOX_PROTOCOLS,
    IncomingMailConnection,
    MessageRef,
    OdooIMAP4,
    connect,
    default_port,
)

if typing.TYPE_CHECKING:
    from odoo.db.cursor import BaseCursor

    from .mail_mail import MailMail
    from odoo.addons.base.models.ir_model import IrModel

_logger = logging.getLogger(__name__)

MAIL_SERVER_DOMAIN = (
    Domain("state", "=", "done")
    & Domain("server_type", "!=", "local")
    & Domain("active", "=", True)
)
MAIL_SERVER_DEACTIVATE_TIME = datetime.timedelta(days=5)

SERVER_TEARDOWN_BUDGET = 4

FETCH_ORDER = "priority asc, date asc nulls first, id asc"


class _FetchOutcome(typing.NamedTuple):
    remaining: int
    exception: Exception | None


class _MessageSink(typing.NamedTuple):
    thread: models.Model
    options: ValuesType

    @property
    def cr(self) -> BaseCursor:
        return self.thread.env.cr

    def process(self, message: bytes) -> None:
        self.thread.message_process(message=message, **self.options)


class _MessageOutcome(enum.Enum):
    DELIVERED = "delivered"
    REFUSED = "refused"
    UNACKNOWLEDGED = "unacknowledged"


CONNECTION_ERROR_MESSAGES = (
    (UnicodeError, lambda e: _("Invalid server name!\n %s", e)),
    (
        (TimeoutError, gaierror),
        lambda e: _(
            "No response received. Check the server address and port number.\n %s",
            e,
        ),
    ),
    (
        SSLCertVerificationError,
        lambda e: _(
            "The server's certificate could not be validated. Check the "
            "server name, or lower Connection Encryption to "
            '"encryption only" if this server has no valid certificate.\n %s',
            e,
        ),
    ),
    (
        SSLError,
        lambda e: _(
            "An SSL exception occurred. Check the Connection Encryption "
            "setting against the port number.\n %s",
            e,
        ),
    ),
    (
        ConnectionError,
        lambda e: _(
            "Could not establish a connection. Check the port number, and "
            "that the server is reachable and accepts connections from this "
            "machine.\n %s",
            e,
        ),
    ),
    (
        (OdooIMAP4.abort, OdooIMAP4.error),
        lambda e: _("The IMAP server replied with an error:\n %s", e),
    ),
    (
        poplib.error_proto,
        lambda e: _("The POP server replied with an error:\n %s", e),
    ),
    (
        OSError,
        lambda e: _(
            "The connection to the server failed. Check the server address, "
            "the port number and your network.\n %s",
            e,
        ),
    ),
)


class FetchmailServer(models.Model):
    _name = "fetchmail.server"
    _description = "Incoming Mail Server"
    _order = "priority"
    _email_field = "user"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    state = fields.Selection(
        [
            ("draft", "Not Confirmed"),
            ("done", "Confirmed"),
        ],
        string="Status",
        index=True,
        readonly=True,
        copy=False,
        default="draft",
    )
    server = fields.Char(string="Server Name", help="Hostname or IP of the mail server")
    port = fields.Integer()
    server_type = fields.Selection(
        [
            ("imap", "IMAP Server"),
            ("pop", "POP Server"),
            ("local", "Local Server"),
        ],
        string="Server Type",
        index=True,
        required=True,
        default="imap",
    )
    server_type_info = fields.Text(
        "Server Type Info", compute="_compute_server_type_info"
    )
    encryption = fields.Selection(
        ENCRYPTION_SELECTION,
        string="Connection Encryption",
        required=True,
        default="ssl_strict",
        help="Choose the connection encryption scheme:\n"
        "- None: the session, including your password, is sent in cleartext.\n"
        "- TLS (STARTTLS): encryption is negotiated on the standard port (IMAP=143, POP3=110)\n"
        "- SSL/TLS: the session is encrypted from the first byte on a dedicated "
        "port (IMAPS=993, POP3S=995)\n"
        "\n"
        "Choose an additional variant for SSL or TLS:\n"
        "- encryption and validation: encrypt and authenticate the server using its "
        "certificate (Recommended)\n"
        "- encryption only: encrypt but accept any certificate, which cannot detect "
        "an impostor server",
    )
    attach = fields.Boolean(
        "Keep Attachments",
        help="Whether attachments should be downloaded. "
        "If not enabled, incoming emails will be stripped of any attachments before being processed",
        default=True,
    )
    original = fields.Boolean(
        "Keep Original",
        help="Whether a full original copy of each email should be kept for reference "
        "and attached to each processed message. This will usually double the size of your message database.",
    )
    date = fields.Datetime(
        string="Last Fetch Attempt",
        readonly=True,
        help="When this server was last polled, whether or not the poll succeeded.",
    )
    error_since = fields.Datetime(
        string="Failing Since",
        readonly=True,
        help="Start of the current run of failures, cleared by the first successful "
        "fetch. A server that keeps failing for longer than five days is "
        "unconfirmed automatically.",
    )
    error_message = fields.Text(
        string="Last Error Message",
        readonly=True,
        help="The most recent failure, cleared by the first successful fetch.",
    )
    user = fields.Char(string="Username", groups="base.group_system")
    password = fields.Char(groups="base.group_system")
    object_id: IrModel = fields.Many2one(
        "ir.model",
        string="Create a New Record",
        help="Process each incoming mail as part of a conversation "
        "corresponding to this document type. This will create "
        "new documents for new conversations, or attach follow-up "
        "emails to the existing conversations (documents).",
        domain=[
            ("is_mail_thread", "=", True),
            ("abstract", "=", False),
            ("transient", "=", False),
        ],
    )
    priority = fields.Integer(
        string="Server Priority",
        help="Defines the order of processing, lower values mean higher priority",
        default=5,
    )
    message_ids: MailMail = fields.One2many(
        "mail.mail",
        "fetchmail_server_id",
        string="Outgoing Mails",
        readonly=True,
        help="Mails sent while processing what this server delivered.",
    )
    configuration = fields.Text(
        "Configuration", compute="_compute_configuration", readonly=True
    )
    script = fields.Char(readonly=True, default="/mail/static/scripts/odoo-mailgate.py")

    @api.depends("server_type")
    def _compute_server_type_info(self) -> None:
        for server in self:
            if server.server_type == "local":
                server.server_type_info = _(
                    "Use a local script to fetch your emails and create new records."
                )
            else:
                server.server_type_info = False

    @api.depends("server_type")
    @api.depends_context("uid")
    def _compute_configuration(self) -> None:
        dbname = self.env.cr.dbname
        uid = self.env.uid
        for server in self:
            if server.server_type != "local":
                server.configuration = False
                continue
            server.configuration = f"""\
Use the below script with the following command line options with your Mail Transport Agent (MTA)
odoo-mailgate.py --host=HOSTNAME --port=PORT -u {uid} -p PASSWORD -d {dbname}

A password passed as -p sits in the process table, where every local user can
read it; --password-file=/etc/odoo/mailgate.secret keeps it out. --retry-status
asks the MTA to queue a message rather than bounce it when Odoo is unreachable,
which is what a restart looks like from here.

Example configuration for the postfix mta running locally:
/etc/postfix/virtual_aliases: @youdomain odoo_mailgate@localhost
/etc/aliases:
odoo_mailgate: "|/path/to/odoo-mailgate.py --host=localhost -u {uid} --password-file=/etc/odoo/mailgate.secret -d {dbname} --retry-status"
"""

    @api.onchange("server_type", "encryption")
    def _onchange_server_type(self) -> None:
        self.update(self._prepare_server_type_defaults())

    def _prepare_server_type_defaults(self) -> ValuesType:
        self.ensure_one()
        return {"port": default_port(self.server_type, self.encryption)}

    @api.model_create_multi
    def create(self, vals_list: list[ValuesType]) -> Self:
        res = super().create(vals_list)
        self._update_cron(vals_list)
        return res

    def write(self, vals: ValuesType) -> Literal[True]:
        res = super().write(vals)
        self._update_cron([vals])
        return res

    def unlink(self) -> Literal[True]:
        res = super().unlink()
        self._update_cron()
        return res

    def set_draft(self) -> bool:
        self.write({"state": "draft", **self._prepare_cleared_error_vals()})
        return True

    def button_confirm_login(self) -> dict[str, Any]:
        self.check_access("write")
        for server in self:
            connection = None
            try:
                connection = server._connect__(allow_archived=True)
                server.write({"state": "done", **server._prepare_cleared_error_vals()})
            except UserError:
                raise
            except Exception as err:
                raise server._connection_test_error(err) from err
            finally:
                if connection is not None:
                    try:
                        connection.disconnect()
                    except Exception:
                        _logger.info(
                            "Failed to close the test connection to %s.",
                            server.name,
                            exc_info=True,
                        )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "message": _("Connection Test Successful!"),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def fetch_mail(self) -> None:
        self.ensure_one().check_access("write")
        if not self.filtered_domain(MAIL_SERVER_DOMAIN):
            raise UserError(
                _(
                    'Server "%s" cannot be polled: only a confirmed IMAP or POP '
                    "server fetches mail.",
                    self.display_name,
                )
            )
        exception = self.sudo()._fetch_mail()
        if exception is not None:
            raise exception

    def _get_connection_type(self) -> str:
        self.ensure_one()
        return self.server_type

    def _connect__(self, allow_archived: bool = False) -> IncomingMailConnection:
        self.ensure_one()
        if not allow_archived and not self.active:
            raise UserError(
                _(
                    'The server "%s" cannot be used because it is archived.',
                    self.display_name,
                )
            )
        connection_type = self._get_connection_type()
        if connection_type not in MAILBOX_PROTOCOLS:
            raise UserError(
                _(
                    'Server "%(name)s" is a %(kind)s server: it does not connect to a '
                    "mailbox.",
                    name=self.display_name,
                    kind=connection_type,
                )
            )
        if self.server_type in MAILBOX_PROTOCOLS and (
            missing := [
                name
                for name, value in (("Server Name", self.server), ("Port", self.port))
                if not value
            ]
        ):
            raise UserError(
                _(
                    'Server "%(name)s" cannot be reached: %(fields)s is not set.',
                    name=self.display_name,
                    fields=", ".join(missing),
                )
            )
        connection = connect(connection_type, self.server, self.port, self.encryption)
        if connection_type == "imap":
            self._imap_login__(connection)
        else:
            connection.user(self.user)
            connection.pass_(self.password)
        return connection

    def _imap_login__(self, connection: OdooIMAP4) -> None:
        self.ensure_one()
        connection.login(self.user, self.password)

    def _connection_test_error(self, exc: Exception) -> UserError:
        self.ensure_one()
        for exc_types, make_message in CONNECTION_ERROR_MESSAGES:
            if isinstance(exc, exc_types):
                return UserError(make_message(exc))
        _logger.warning(
            "Connection test on %s server %s failed with an unexpected error.",
            self.server_type,
            self.name,
            exc_info=exc,
        )
        return UserError(
            _("Connection Test Failed! Check the server log for the full error.")
        )

    def _prepare_cleared_error_vals(self) -> ValuesType:
        return {"error_since": False, "error_message": False}

    def _register_fetch_failure(self, exc: Exception) -> None:
        self.ensure_one()
        now = fields.Datetime.now()
        self.error_message = str(exc) or repr(exc)
        if not self.error_since:
            self.error_since = now
        elif self.error_since < now - MAIL_SERVER_DEACTIVATE_TIME:
            message = "Deactivating fetchmail %s server %s (too many failures)" % (
                self.server_type,
                self.name,
            )
            self.set_draft()
            self.env["ir.cron"]._notify_admin(message)

    @api.model
    def _fetch_mails(self, **kw) -> None:
        if (
            self.env.context.get("cron_id")
            != self.env.ref("mail.ir_cron_mail_gateway_action").id
        ):
            raise ValueError("_fetch_mails is meant for cron usage only")
        records = self.search(MAIL_SERVER_DOMAIN, order=FETCH_ORDER)
        time_buffer = self.env.context["cron_end_time"] + (
            SERVER_TEARDOWN_BUDGET * len(records)
        )
        records.with_context(cron_end_time=time_buffer)._fetch_mail(**kw)
        if not self.search_count(MAIL_SERVER_DOMAIN):
            self.env["ir.cron"]._commit_progress(deactivate=True)

    def _fetch_mail(self, batch_limit: int = 50) -> Exception | None:
        result_exception = None
        servers = self.with_context(fetchmail_cron_running=True)
        commit_progress = self.env["ir.cron"]._commit_progress
        total_remaining = len(servers)
        commit_progress(0, remaining=total_remaining)
        _logger.info(
            "Fetchmail servers (in order) to be processed %s", servers.mapped("name")
        )

        for server in servers:
            total_remaining -= 1
            if not server.try_lock_for_update(allow_referencing=True).filtered_domain(
                MAIL_SERVER_DOMAIN
            ):
                _logger.info(
                    "Skip checking for new mails on mail server id %d (unavailable)",
                    server.id,
                )
                commit_progress(0, remaining=total_remaining)
                continue
            outcome = server._poll_mailbox(batch_limit, total_remaining)
            total_remaining = outcome.remaining
            if outcome.exception is not None:
                result_exception = outcome.exception
            server.date = fields.Datetime.now()
            server.env.cr.commit()
            if not commit_progress(1, remaining=total_remaining):
                break
        return result_exception

    def _poll_mailbox(self, batch_limit: int, remaining: int) -> _FetchOutcome:
        self.ensure_one()
        label = (self.server_type, self.name)
        _logger.info("Start checking for new emails on %s server %s", *label)
        beyond_this_server = remaining
        outcomes = collections.Counter()
        count = announced = 0
        interrupted = False
        connection = None
        message_cr = None
        exception = None
        try:
            connection = self._connect__()
            message_cr = self.env.registry.cursor()
            sink = self._prepare_message_sink(message_cr)
            commit_progress = sink.thread.env["ir.cron"]._commit_progress
            announced = connection.check_unread_messages()
            _logger.debug("%d unread messages on %s server %s.", announced, *label)
            for num, message in connection.retrieve_unread_messages():
                _logger.debug("Fetched message %r on %s server %s.", num, *label)
                count += 1
                outcomes[
                    self._process_one_message(sink, connection, num, message, label)
                ] += 1
                remaining = max(beyond_this_server + announced - count, 0)
                time_left = commit_progress(1, remaining=remaining)
                if count >= batch_limit or not time_left:
                    interrupted = True
                    break
            self.write(self._prepare_cleared_error_vals())
        except Exception as exc:
            exception = exc
            _logger.info(
                "General failure when trying to fetch mail from %s server %s.",
                *label,
                exc_info=True,
            )
            self._register_fetch_failure(exc)
        finally:
            if message_cr is not None:
                message_cr.close()
            if connection is not None:
                try:
                    connection.disconnect()
                except Exception:
                    _logger.warning(
                        "Failed to properly finish the %s connection to %s.",
                        *label,
                        exc_info=True,
                    )
        if count > announced:
            _logger.warning(
                "The %s connection to %s announced %d unread message(s) and "
                "yielded %d.",
                *label,
                announced,
                count,
            )
        undelivered = max(announced - count, 0) if interrupted else 0
        _logger.info(
            "Fetched %d email(s) on %s server %s; %d delivered, %d refused, "
            "%d delivered but not acknowledged.",
            count,
            *label,
            outcomes[_MessageOutcome.DELIVERED],
            outcomes[_MessageOutcome.REFUSED],
            outcomes[_MessageOutcome.UNACKNOWLEDGED],
        )
        return _FetchOutcome(
            remaining=beyond_this_server + undelivered, exception=exception
        )

    def _prepare_message_sink(self, message_cr: BaseCursor) -> _MessageSink:
        self.ensure_one()
        return _MessageSink(
            thread=self.env["mixin.mail.thread"]
            .with_env(self.env(cr=message_cr))
            .with_context(default_fetchmail_server_id=self.id),
            options={
                "model": self.object_id.model,
                "save_original": self.original,
                "strip_attachments": not self.attach,
            },
        )

    def _process_one_message(
        self,
        sink: _MessageSink,
        connection: IncomingMailConnection,
        num: MessageRef,
        message: bytes,
        label: tuple[str, str],
    ) -> _MessageOutcome:
        try:
            sink.process(message)
            sink.cr.commit()
        except Exception:
            sink.cr.rollback()
            _logger.info(
                "Failed to process mail from %s server %s.", *label, exc_info=True
            )
            return _MessageOutcome.REFUSED
        try:
            connection.handled_message(num)
        except Exception:
            _logger.warning(
                "Processed message %r on %s server %s but could not acknowledge it; "
                "the server will deliver it again.",
                num,
                *label,
                exc_info=True,
            )
            return _MessageOutcome.UNACKNOWLEDGED
        return _MessageOutcome.DELIVERED

    _CRON_RELEVANT_FIELDS = frozenset({"state", "server_type", "active"})

    @api.model
    def _update_cron(self, vals_list: list[ValuesType] | None = None) -> None:
        if self.env.context.get("fetchmail_cron_running"):
            return
        if vals_list is not None and not any(
            self._CRON_RELEVANT_FIELDS & vals.keys() for vals in vals_list
        ):
            return
        try:
            cron = self.env.ref("mail.ir_cron_mail_gateway_action")
        except ValueError:
            return
        cron.toggle(model=self._name, domain=MAIL_SERVER_DOMAIN)
