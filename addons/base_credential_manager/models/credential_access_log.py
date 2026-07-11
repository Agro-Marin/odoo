import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class CredentialAccessLog(models.Model):
    """Audit log for credential access tracking.

    Records all credential access for security auditing, compliance,
    and debugging purposes.

    Security: This model is write-once (immutable after creation) to ensure
    audit trail integrity. Records cannot be modified or deleted through
    normal operations.

    ACL note: ``ir.model.access.csv`` intentionally grants zero write/create/
    unlink rights to every group, including ``group_credential_admin``. This
    is deliberate. Log rows are written exclusively by
    ``credential.credential._log_access`` via ``sudo().create(...)``, and
    deletion is gated through ``cron_cleanup_old_logs`` which uses the
    SUPERUSER + context-key bypass above. If you find yourself wanting to
    grant ORM create rights here, you almost certainly want to call
    ``_log_access`` from your code instead.
    """

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
        """Prevent modification of audit log records.

        Security: Audit logs must be immutable to ensure trail integrity.
        Only the 'display_name' field (computed) can change.

        Raises:
            UserError: If attempting to modify protected fields.

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
        """Prevent deletion of audit log records.

        Security: Audit logs must be preserved for compliance and security auditing.
        Only automated cleanup (via cron) with special context can delete old records.

        Raises:
            UserError: If attempting to delete without cleanup context.

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
        """Compute display name for the log entry.

        Falls back to the denormalized credential_name when credential_id has
        been nulled (the credential was deleted), so historic rows remain
        readable instead of rendering as "False - read at ...".
        """
        for record in self:
            if record.timestamp:
                timestamp_str = record.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            else:
                timestamp_str = "Unknown"
            cred_label = record.credential_id.name or record.credential_name or "(deleted)"
            record.display_name = (
                f"{cred_label} - {record.operation} at {timestamp_str}"
            )

    # -------------------------------------------------------------------------
    # CRON METHODS
    # -------------------------------------------------------------------------

    def cron_cleanup_old_logs(self, retention_days: int = 365):
        """Clean up audit logs older than retention period.

        This method is designed to be called by a scheduled action (cron).
        It bypasses the write-once protection using a special context key
        and runs under ``sudo()`` so an operator who retargets the cron to
        a non-superuser service account does not silently lose log cleanup.
        The previous implementation relied on ``self.env.uid == SUPERUSER_ID``
        via the cron being hard-wired to ``base.user_root``; that made the
        cleanup invisible-to-break under a normal ops change.

        Args:
            retention_days: Number of days to retain logs (default: 365)

        Returns:
            int: Number of records deleted

        """
        cutoff_date = fields.Datetime.now() - timedelta(days=retention_days)

        sudo_self = self.sudo()
        old_logs = sudo_self.search([("timestamp", "<", cutoff_date)])
        count = len(old_logs)

        if old_logs:
            # Use cleanup context to bypass immutability protection
            old_logs.with_context(**{self._CLEANUP_CONTEXT_KEY: True}).unlink()

        return count

    # -------------------------------------------------------------------------
    # VALIDATIONS
    # -------------------------------------------------------------------------

    def _is_cleanup_authorized(self) -> bool:
        """Gate the write/unlink bypass used by cron_cleanup_old_logs.

        Two conditions, both necessary:
        1. The cleanup context key is set (rules out accidental ORM writes).
        2. The environment is elevated (``env.su`` is True — i.e. the caller
           went through ``sudo()``). This rules out regular user code paths.

        This used to check ``env.uid == SUPERUSER_ID`` directly, but Odoo 19's
        ``sudo()`` does NOT change ``env.uid`` — it only sets ``env.su``. So a
        cleanly-sudoed cron runner (the normal pattern) kept failing the gate
        and the cleanup silently no-oped. Checking ``env.su`` aligns the gate
        with Odoo's actual privilege-elevation mechanism and lets the cron
        work under any user who reaches the method through ``sudo()``.

        This is an accident-prevention gate, not a security boundary —
        anything running with ``env.su`` can already bypass the Python
        layer anyway. See the class-level threat-model comment.
        """
        if not self.env.context.get(self._CLEANUP_CONTEXT_KEY):
            return False
        if not self.env.su:
            _logger.warning(
                "Audit log cleanup bypass attempted without sudo (uid=%s).",
                self.env.uid,
            )
            return False
        return True
