import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class CredentialAccessLog(models.Model):
    """Write-once audit log of credential access, for security and compliance."""

    # Immutability model (why ir.model.access.csv grants zero write/create/
    # unlink to every group, including group_credential_admin): this model is
    # write-once to keep the audit trail intact. Rows are written only by the
    # credential.credential audit helpers (_log_access / _log_access_out_of_band)
    # via sudo().create(), and deletion is gated through cron_cleanup_old_logs,
    # which uses the sudo() (env.su) + context-key bypass defined below. To
    # record access, call _log_access from your code rather than granting ORM
    # create rights here.

    _name = "credential.access.log"
    _description = "Credential Access Log"
    _order = "timestamp desc"
    _rec_name = "credential_id"

    # Context key to allow automated cleanup to bypass immutability.
    #
    # HONEST THREAT MODEL: This gate protects against *accidents* (a buggy
    # module or operator typo accidentally deleting audit logs), not against
    # an attacker. Anyone with SUPERUSER_ID and a live Python shell can raw-
    # SQL ``DELETE FROM credential_access_log`` or monkey-patch this class;
    # no in-process Python check can stop that. For true write-once audit,
    # add a Postgres trigger or revoke DELETE privilege at the DB role level.
    _CLEANUP_CONTEXT_KEY = "_credential_log_cleanup_bypass"

    company_id = fields.Many2one(
        comodel_name="res.company",
        required=False,
        ondelete="cascade",
        index=True,
        help="Company context for the access (empty for system-wide credentials)",
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        required=False,
        ondelete="set null",
        index=True,
        help="User who accessed the credential. Nullable with ondelete=set "
        "null so deleting a user does NOT erase the audit trail of what they "
        "accessed; the login is denormalized into user_login for readability.",
    )
    user_login = fields.Char(
        string="User Login",
        help="Login of the accessing user, captured at access time. Survives "
        "deletion of the res.users record so the audit row stays readable.",
    )
    credential_id = fields.Many2one(
        comodel_name="credential.credential",
        required=False,
        ondelete="set null",
        index=True,
        help="Credential that was accessed. Nullable with ondelete=set null: "
        "an audit trail MUST outlive the credential it describes, so deleting "
        "a credential nulls this FK instead of cascade-wiping its history. The "
        "name is denormalized into credential_name so the row stays readable.",
    )
    credential_name = fields.Char(
        string="Credential Name",
        index=True,
        help="Name of the accessed credential, captured at access time. "
        "Survives deletion of the credential so the audit row stays readable.",
    )
    operation = fields.Selection(
        selection=[
            ("read", "Read"),
            ("write", "Write"),
            ("validate", "Validate"),
            ("use", "Use"),
            ("delete", "Delete"),
            ("read_rate_limited", "Read (Rate Limited)"),
        ],
        required=True,
        index=True,
        help="Type of operation performed",
    )
    timestamp = fields.Datetime(
        required=True,
        default=fields.Datetime.now,
        index=True,
        help="When the access occurred",
    )
    source_ip = fields.Char(
        string="Source IP",
        index=True,
        help="IP address of the request origin (if available)",
    )
    display_name = fields.Char(
        compute="_compute_display_name",
        store=False,
    )

    _timestamp_credential_idx = models.Index("(timestamp, credential_id)")

    # -------------------------------------------------------------------------
    # CRUD METHODS
    # -------------------------------------------------------------------------

    def write(self, vals):
        """Reject writes to protected fields to keep the audit trail immutable.

        :raises UserError: if modifying any field other than the computed
            ``display_name`` without cleanup authorization.
        """
        # Allow display_name recomputation (it's computed, not stored)
        protected_fields = set(vals.keys()) - {"display_name"}

        if protected_fields and not self._is_cleanup_authorized():
            raise UserError(
                self.env._(
                    "Audit log records cannot be modified!\n\n"
                    "Credential access logs are immutable to ensure audit trail "
                    "integrity. This is a security feature.\n\n"
                    "Attempted to modify: %(fields)s",
                )
                % {"fields": ", ".join(sorted(protected_fields))},
            )

        return super().write(vals)

    def unlink(self):
        """Reject deletion to preserve the audit trail; only cron cleanup may delete.

        :raises UserError: if deleting without cleanup authorization.
        """
        if not self._is_cleanup_authorized():
            raise UserError(  # pylint: disable=raise-unlink-override,no-raise-unlink,E8503
                self.env._(
                    "Audit log records cannot be deleted!\n\n"
                    "Credential access logs must be preserved for security auditing "
                    "and compliance. This is a security feature.\n\n"
                    "If you need to remove old logs, use the automated cleanup "
                    "scheduled action which respects retention policies.",
                ),
            )

        return super().unlink()

    # -------------------------------------------------------------------------
    # COMPUTE METHODS
    # -------------------------------------------------------------------------

    @api.depends("credential_id", "credential_name", "operation", "timestamp")
    def _compute_display_name(self) -> None:
        """Compute the display name, using denormalized fields for deleted credentials."""
        for record in self:
            if record.timestamp:
                timestamp_str = record.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            else:
                timestamp_str = "Unknown"
            # Fall back to the denormalized name when credential_id was nulled
            # (credential deleted) so historic rows stay readable instead of
            # rendering as "False - read at ...".
            cred_label = (
                record.credential_id.name or record.credential_name or "(deleted)"
            )
            record.display_name = (
                f"{cred_label} - {record.operation} at {timestamp_str}"
            )

    # -------------------------------------------------------------------------
    # CRON METHODS
    # -------------------------------------------------------------------------

    def cron_cleanup_old_logs(self, retention_days: int = 365):
        """Delete audit logs older than the retention period (cron entry point).

        :param retention_days: days of logs to retain (default 365)
        :return: number of records deleted
        :rtype: int
        """
        cutoff_date = fields.Datetime.now() - timedelta(days=retention_days)

        # Run under sudo() and set the cleanup context key to bypass the
        # write-once protection. Using sudo() (rather than a cron hard-wired to
        # base.user_root) keeps cleanup working even if an operator retargets
        # the cron to a non-superuser service account; the old
        # env.uid == SUPERUSER_ID gate broke silently under that change.
        sudo_self = self.sudo()
        old_logs = sudo_self.search([("timestamp", "<", cutoff_date)])
        count = len(old_logs)

        if old_logs:
            old_logs.with_context(**{self._CLEANUP_CONTEXT_KEY: True}).unlink()

        return count

    # -------------------------------------------------------------------------
    # VALIDATIONS
    # -------------------------------------------------------------------------

    def _is_cleanup_authorized(self) -> bool:
        """Gate the write/unlink bypass used by cron_cleanup_old_logs.

        :return: True only when the cleanup context key is present and the
            environment is elevated (``env.su``).
        :rtype: bool
        """
        # Both conditions are necessary: the context key rules out accidental
        # ORM writes; env.su rules out regular user code paths.
        #
        # Gate on env.su, not env.uid == SUPERUSER_ID: Odoo 19's sudo() does not
        # change env.uid, it only sets env.su, so the old uid check made a
        # cleanly-sudoed cron silently fail and no-op. This is an accident-
        # prevention gate, not a security boundary — anything with env.su can
        # already bypass the Python layer (see the class-level threat model).
        if not self.env.context.get(self._CLEANUP_CONTEXT_KEY):
            return False
        if not self.env.su:
            _logger.warning(
                "Audit log cleanup bypass attempted without sudo (uid=%s).",
                self.env.uid,
            )
            return False
        return True
