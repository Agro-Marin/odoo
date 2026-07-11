import base64
import contextlib
import hashlib
import ipaddress
import json
import logging
import re
from typing import Any

from cryptography import x509
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.serialization import Encoding, pkcs12
from psycopg import errors as psycopg_errors

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

from odoo.addons.base_credential_manager.tools import (
    get_credential_rate_limiter,
)

_logger = logging.getLogger(__name__)


# Security limits for credential data validation
MAX_CREDENTIAL_DATA_SIZE = 65536  # 64KB max for JSON credential data
MAX_CREDENTIAL_VALUE_SIZE = 8192  # 8KB max for simple credential values
MAX_JSON_NESTING_DEPTH = 10  # Maximum nesting depth for JSON data


def _check_json_depth(obj: Any, current_depth: int = 0) -> int:
    """Check the maximum nesting depth of a JSON-like object.

    Args:
        obj: The object to check (dict, list, or primitive)
        current_depth: Current recursion depth

    Returns:
        int: Maximum depth found

    Raises:
        ValueError: If depth exceeds MAX_JSON_NESTING_DEPTH

    """
    if current_depth > MAX_JSON_NESTING_DEPTH:
        raise ValueError(
            f"JSON nesting depth exceeds maximum allowed ({MAX_JSON_NESTING_DEPTH})",
        )

    if isinstance(obj, dict):
        if not obj:
            return current_depth
        return max(_check_json_depth(v, current_depth + 1) for v in obj.values())
    if isinstance(obj, list):
        if not obj:
            return current_depth
        return max(_check_json_depth(v, current_depth + 1) for v in obj)
    return current_depth


# Patterns that suggest secrets in notes field (case-insensitive)
# These trigger a warning, not an error.
# Each entry is (name, pattern); ``name`` is a safe label that identifies
# WHICH kind of secret was detected without ever exposing the matched value.
# Note: Using re.IGNORECASE instead of inline (?i) flags because inline flags
# must be at start of pattern when joining with |.
SECRET_PATTERNS = [
    ("password", r"\b(password|passwd|pwd)\s*[:=]\s*\S+"),  # password=xxx
    ("api_key", r"\b(api[_-]?key|apikey)\s*[:=]\s*\S+"),  # api_key: xxx
    ("secret_or_token", r"\b(secret|token)\s*[:=]\s*\S+"),  # secret: xxx
    ("aws_style_key", r"\b(access[_-]?key|secret[_-]?key)\s*[:=]\s*\S+"),
    ("private_key_pem", r"-----BEGIN\s+\w+\s+PRIVATE\s+KEY-----"),
    ("github_token", r"\bghp_[a-zA-Z0-9]{36}\b"),
    ("openai_api_key", r"\bsk-[a-zA-Z0-9]{48}\b"),
    ("aws_access_key_id", r"\bAKIA[0-9A-Z]{16}\b"),
]
# Per-pattern compiled regexes so we can name the match without exposing the
# secret value; used by _check_notes_for_secrets to log a pattern name only.
SECRET_NAMED_REGEXES = [
    (name, re.compile(pattern, re.IGNORECASE)) for name, pattern in SECRET_PATTERNS
]


# Maps category_code to required field configurations.
#
# Each entry: {'fields': [<spec>, ...], 'message': '...'}
#
# A <spec> is EITHER:
#   * a str — a single field that must be filled (AND against siblings), OR
#   * a tuple — a set of alternatives, any one of which satisfies the slot.
#
# The tuple form exists because single-payload categories (api_key,
# bearer_token) support two storage modes per the write-once storage_method
# invariant: simple (credential_value) or JSON accessor (api_key /
# bearer_token). Pre-fix this config listed only "credential_value" and the
# validator rejected JSON-mode credentials whose payload lives under the
# accessor JSON key rather than a "credential_value" key. See t21134 F1b.
CATEGORY_REQUIRED_FIELDS = {
    "api_key": {
        "fields": [("credential_value", "api_key")],
        "message": "API Key credentials require a secret value.",
    },
    "bearer_token": {
        "fields": [("credential_value", "bearer_token")],
        "message": "Bearer Token credentials require a token value.",
    },
    "basic_auth": {
        "fields": ["username", "password"],
        "message": "Basic Authentication requires username and password.",
    },
    "oauth2": {
        "fields": ["oauth_access_token"],  # At minimum, access token required
        "message": "OAuth 2.0 credentials require at least an access token.",
    },
    "aws_iam": {
        "fields": ["api_key", "api_secret"],
        "message": "AWS IAM credentials require Access Key ID and Secret Access Key.",
    },
    "certificate": {
        "fields": ["certificate_content"],
        "message": "Certificate credentials require a certificate file.",
    },
    # 'custom' has no required fields - it's flexible
}


class CredentialCredential(models.Model):
    """Credential storage model with encrypted data.

    This model provides:
    - Encrypted credential storage (Fernet AES-128)
    - Category-based classification
    - Multi-company isolation
    - Credential validation framework
    - Health monitoring
    - Audit logging
    - Certificate/key management for certificate-type credentials
    """

    _name = "credential.credential"
    _inherit = "credential.encryption.mixin"
    _description = "Credential"
    _order = "company_id, sequence, name"
    _rec_name = "name"

    # ------------------------------------------------------------
    # FIELDS
    # ------------------------------------------------------------

    company_id = fields.Many2one(
        comodel_name="res.company",
        required=False,
        default=lambda self: self.env.company,
        ondelete="cascade",
        index=True,
        help="Company that owns this credential. Leave empty for system-wide credentials visible to all companies.",
    )

    category_id = fields.Many2one(
        comodel_name="credential.category",
        required=True,
        index=True,
        ondelete="restrict",
        help="Type of credential (API Key, OAuth, Certificate, etc.)",
    )
    category_code = fields.Char(
        related="category_id.code",
        store=True,
        index=True,
        help="Technical code of the category for programmatic access",
    )
    category_description = fields.Text(
        related="category_id.description",
        store=False,
        help="Description of the credential category",
    )
    category_icon = fields.Char(
        related="category_id.icon",
        store=False,
    )
    storage_hint = fields.Selection(
        related="category_id.storage_hint",
        string="Storage Type",
        store=False,
        help="Recommended storage method from category",
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Created By",
        default=lambda self: self.env.user,
        readonly=True,
        index=True,
        help="User who created this credential",
    )
    name = fields.Char(
        string="Credential Name",
        required=True,
        index=True,
        help="Descriptive name for this credential",
    )
    active = fields.Boolean(
        default=True,
        help="Only active credentials are used. Archiving is an admin-only "
        "control enforced by record rules / access rights — a field-level "
        "``groups=`` cannot be used here because the ORM's active_test reads "
        "``active`` on every search (including for plain users).",
    )
    sequence = fields.Integer(
        string="Priority",
        default=10,
        help="Lower number = higher priority when multiple credentials exist",
    )
    display_name = fields.Char(
        compute="_compute_display_name",
        store=False,
    )
    username = fields.Char(
        compute="_compute_credential_accessors",
        inverse="_inverse_credential_field_username",
        copy=False,
        groups="base.group_system",
        help="Username stored in JSON credential data",
    )
    password = fields.Char(
        compute="_compute_credential_accessors",
        inverse="_inverse_credential_field_password",
        copy=False,
        groups="base.group_system",
        help="Password stored in JSON credential data",
    )
    notes = fields.Text(
        help="Additional notes or documentation for this credential.\n\n"
        "⚠️ SECURITY WARNING: Notes are stored in PLAIN TEXT (not encrypted).\n"
        "Do NOT store passwords, API keys, or other secrets in notes.",
    )

    # ==================== Encrypted Storage ====================

    credential_value_encrypted = fields.Binary(
        string="Credential Value (Encrypted)",
        copy=False,
        attachment=False,
        groups="base.group_system",
        help="Encrypted storage for credential value (API key, token, secret, etc.)",
    )
    # Private decryption memo. Not exposed to users. The three credential-
    # payload compute fields (credential_value, credential_data,
    # storage_method) all derive from this one rather than each calling
    # _decrypt_value independently. Odoo's compute-cache memoizes this once
    # per transaction, so opening a form triggers one Fernet.decrypt instead
    # of three. See M1 in the investigation notes.
    cached_plaintext = fields.Char(
        compute="_compute_cached_plaintext",
        store=False,
        copy=False,
        groups="base.group_system",
        help="Internal: single-decrypt memo for credential_value_encrypted. "
        "Do NOT depend on this field outside this model.",
    )
    # Storage mode is a write-once invariant. It is set by the FIRST inverse
    # that actually writes credential payload (credential_value -> 'simple',
    # any JSON accessor or credential_data -> 'json') and never transitions
    # after that. Attempting to write through the opposite mode raises
    # ValidationError. This closes the silent-mutation data-loss path where
    # writing a JSON accessor on a simple credential would re-encrypt the
    # payload as {"value": <simple>, <field>: <new>} and break future reads
    # of credential_value. See TestSimpleToJsonStorageTransition.
    storage_method = fields.Selection(
        selection=[
            ("none", "Not Set"),
            ("simple", "Simple Value"),
            ("json", "JSON Data"),
        ],
        default="none",
        store=True,
        readonly=True,
        copy=False,
        help="Storage mode for credential_value_encrypted. Write-once: set "
        "by the first payload write and sealed thereafter. Mixing simple "
        "and JSON storage on the same record is not permitted.",
    )
    credential_value = fields.Char(
        compute="_compute_credential_value",
        store=False,
        inverse="_inverse_credential_value",
        readonly=False,
        copy=False,
        groups="base.group_system",
        help="Credential value (encrypted at rest) - API key, bearer token, etc.",
    )
    credential_data = fields.Text(
        string="Credential Data (JSON)",
        compute="_compute_credential_data",
        store=False,
        inverse="_inverse_credential_data",
        readonly=False,
        copy=False,
        groups="base.group_system",
        help="JSON storage for complex multi-value credentials (e.g., OAuth2). "
        "Example: {'access_token': '...', 'refresh_token': '...'}",
    )

    # ==================== Certificate Fields (for certificate category) ====================

    # Encrypted storage for certificate file (security: PKCS12 files contain private keys)
    certificate_content_encrypted = fields.Binary(
        string="Certificate (Encrypted)",
        copy=False,
        attachment=False,
        groups="base.group_system",
        help="Encrypted storage for certificate file content",
    )
    certificate_content = fields.Binary(
        string="Certificate",
        compute="_compute_certificate_content",
        inverse="_inverse_certificate_content",
        store=False,
        copy=False,
        attachment=False,
        groups="base.group_system",
        help="Certificate file content (DER, PEM, or PKCS12 format)",
    )
    certificate_filename = fields.Char(
        help="Original filename of the uploaded certificate",
    )
    certificate_password_encrypted = fields.Binary(
        string="Certificate Password (Encrypted)",
        copy=False,
        attachment=False,
        groups="base.group_system",
        help="Encrypted storage for certificate/PKCS12 password",
    )
    certificate_password = fields.Char(
        compute="_compute_certificate_password",
        inverse="_inverse_certificate_password",
        store=False,
        copy=False,
        groups="base.group_system",
        help="Password for encrypted certificate/PKCS12 file",
    )
    certificate_pem = fields.Binary(
        string="Certificate (PEM)",
        compute="_compute_certificate_pem",
        store=False,  # SECURITY: Don't store - compute from encrypted source on demand
        help="Certificate in PEM format (computed from encrypted content)",
    )
    certificate_format = fields.Selection(
        selection=[
            ("der", "DER"),
            ("pem", "PEM"),
            ("pkcs12", "PKCS12"),
        ],
        compute="_compute_certificate_data",
        store=True,
        help="Detected format of the uploaded certificate",
    )
    certificate_subject = fields.Char(
        string="Subject",
        compute="_compute_certificate_data",
        store=True,
        help="Certificate subject common name",
    )
    certificate_serial = fields.Char(
        string="Serial Number",
        compute="_compute_certificate_data",
        store=True,
        help="Certificate serial number",
    )
    certificate_date_start = fields.Datetime(
        string="Valid From",
        compute="_compute_certificate_data",
        store=True,
        help="Certificate validity start date",
    )
    certificate_date_end = fields.Datetime(
        string="Valid Until",
        compute="_compute_certificate_data",
        store=True,
        help="Certificate validity end date",
    )
    certificate_is_valid = fields.Boolean(
        string="Certificate Valid",
        compute="_compute_certificate_is_valid",
        store=False,
        help="Whether the certificate is currently valid (within date range)",
    )
    certificate_loading_error = fields.Text(
        string="Certificate Error",
        compute="_compute_certificate_data",
        store=True,
        help="Error message if certificate could not be loaded",
    )
    private_key_content_encrypted = fields.Binary(
        string="Private Key (Encrypted)",
        copy=False,
        attachment=False,
        groups="base.group_system",
        help="Encrypted storage for private key file content",
    )
    private_key_content = fields.Binary(
        string="Private Key",
        compute="_compute_private_key_content",
        inverse="_inverse_private_key_content",
        store=False,
        copy=False,
        groups="base.group_system",
        help="Private key file content (auto-extracted from PKCS12 or uploaded separately)",
    )
    private_key_filename = fields.Char(
        help="Original filename of the uploaded private key",
    )
    private_key_pem = fields.Binary(
        string="Private Key (PEM)",
        compute="_compute_private_key_pem",
        store=False,  # SECURITY: NEVER store private keys unencrypted!
        groups="base.group_system",
        help="Private key in PEM format (computed from encrypted source on demand)",
    )

    # ==================== Health & Monitoring ====================

    health_status = fields.Selection(
        selection=[
            ("unknown", "Unknown"),
            ("healthy", "Healthy"),
            ("warning", "Warning"),  # Also known as "degraded" in some contexts
            ("error", "Error"),  # Also known as "unhealthy" in some contexts
        ],
        default="unknown",
        readonly=True,
        index=True,
        help="Health status from last validation check",
    )
    health_message = fields.Text(
        readonly=True,
        help="Details from last health check",
    )
    last_health_check = fields.Datetime(
        readonly=True,
        help="Timestamp of most recent health check",
    )
    last_health_check_latency = fields.Float(
        string="Last Check Latency (ms)",
        readonly=True,
        digits=(6, 2),
        help="Response time of last health check in milliseconds",
    )
    last_used_at = fields.Datetime(
        string="Last Used",
        readonly=True,
        help="Timestamp of most recent credential usage",
    )
    last_error = fields.Text(
        readonly=True,
        help="Error message from last failed operation",
    )
    last_error_date = fields.Datetime(
        readonly=True,
        help="Date and time of last error",
    )
    total_health_checks = fields.Integer(
        default=0,
        readonly=True,
        help="Total number of health check tests performed",
    )
    failed_health_checks = fields.Integer(
        default=0,
        readonly=True,
        help="Number of failed health check tests",
    )
    health_check_success_rate = fields.Float(
        string="Health Check Success Rate (%)",
        compute="_compute_health_check_success_rate",
        store=True,
        digits=(5, 2),
        help="Percentage of successful health checks",
    )

    # ==================== Usage Statistics ====================

    usage_count = fields.Integer(
        default=0,
        readonly=True,
        help="Total number of times this credential was used",
    )
    success_count = fields.Integer(
        default=0,
        readonly=True,
        help="Number of successful credential uses",
    )
    error_count = fields.Integer(
        default=0,
        readonly=True,
        help="Number of failed credential uses",
    )
    success_rate = fields.Float(
        string="Success Rate (%)",
        compute="_compute_success_rate",
        store=True,
        help="Percentage of successful credential uses",
    )

    # ==================== Expiration Tracking ====================

    date_expiration = fields.Datetime(
        string="Expires At",
        help="Date when this credential expires (optional)",
    )
    is_expired = fields.Boolean(
        string="Expired",
        compute="_compute_is_expired",
        store=True,
        help="Whether the credential has expired. Note: This is stored for indexing "
        "but only recomputes when date_expiration changes. For time-critical queries, "
        "filter directly on date_expiration < now().",
    )
    # Constant for "no expiration" days value (used in days_until_expiry)
    DAYS_NO_EXPIRY = 999

    days_until_expiry = fields.Integer(
        compute="_compute_days_until_expiry",
        help=f"Number of days until credential expires. Returns {999} if no expiration date is set.",
    )

    # ==================== Cache Statistics ====================

    cache_hits = fields.Integer(
        default=0,
        readonly=True,
        help="Number of times a cached session/connection was reused",
    )
    cache_misses = fields.Integer(
        default=0,
        readonly=True,
        help="Number of times a new session/connection had to be created",
    )
    encryption_key_version = fields.Integer(
        readonly=True,
        help="Version of encryption key used (for key rotation tracking)",
    )
    allow_key_fallback = fields.Boolean(
        string="Allow Old Key Fallback",
        default=True,
        help="If enabled, will try decrypting with old key versions when current key fails. "
        "Default from category, can be overridden.",
    )
    auto_validate_health = fields.Boolean(
        string="Automatic Health Validation",
        default=False,
        help="If enabled, this credential will be automatically validated by scheduled health checks. "
        "Default from category, can be overridden.",
    )

    enable_rate_limiting = fields.Boolean(
        default=True,
        groups="base_credential_manager.group_credential_admin",
        help="Enable rate limiting for credential access operations. Default from category, can be overridden.",
    )
    rate_limit_max_attempts = fields.Integer(
        string="Rate Limit (attempts/hour)",
        default=100,
        groups="base_credential_manager.group_credential_admin",
        help="Maximum number of decryption operations allowed per user per hour. "
        "Default from category, can be overridden.",
    )

    # ==================== Environment ====================

    environment = fields.Selection(
        selection=[
            ("test", "Test/Sandbox"),
            ("staging", "Staging"),
            ("production", "Production"),
        ],
        default="test",
        index=True,
        help="Environment for this credential (test, staging, production).",
    )

    is_system_wide = fields.Boolean(
        string="System-wide Configuration",
        compute="_compute_is_system_wide",
        store=True,
        help="True if this is a system-wide credential (company_id is not set)",
    )
    bypass_format_validation = fields.Boolean(
        default=False,
        groups="base.group_system",
        help="Allow non-standard credential formats. Use only for credentials with unusual format requirements.",
    )

    # ==================== Computed Credential Fields (JSON Accessors) ====================

    api_key = fields.Char(
        string="API Key",
        compute="_compute_credential_accessors",
        inverse="_inverse_credential_field_api_key",
        copy=False,
        groups="base.group_system",
        help="API Key stored in JSON credential data",
    )
    api_secret = fields.Char(
        string="API Secret",
        compute="_compute_credential_accessors",
        inverse="_inverse_credential_field_api_secret",
        copy=False,
        groups="base.group_system",
        help="API Secret stored in JSON credential data",
    )
    bearer_token = fields.Char(
        compute="_compute_credential_accessors",
        inverse="_inverse_credential_field_bearer_token",
        copy=False,
        groups="base.group_system",
        help="Bearer Token stored in JSON credential data",
    )

    # ==================== OAuth Fields ====================

    oauth_access_token = fields.Char(
        string="OAuth Access Token",
        compute="_compute_credential_accessors",
        inverse="_inverse_credential_field_oauth_access_token",
        copy=False,
        groups="base.group_system",
        help="OAuth Access Token stored in JSON credential data",
    )
    oauth_refresh_token = fields.Char(
        string="OAuth Refresh Token",
        compute="_compute_credential_accessors",
        inverse="_inverse_credential_field_oauth_refresh_token",
        copy=False,
        groups="base.group_system",
        help="OAuth Refresh Token stored in JSON credential data",
    )
    oauth_token_date_expiration = fields.Datetime(
        string="OAuth Token Expiration",
        groups="base.group_system",
        help="When the OAuth access token expires. Set by OAuth integration code "
        "when tokens are refreshed (comes from provider's 'expires_in' response).",
    )

    # ==================== Credential Metadata ====================

    credential_hash = fields.Char(
        compute="_compute_credential_hash",
        store=True,
        readonly=True,
        help="Hash of encrypted credentials for cache key generation and integrity",
    )
    last_validated = fields.Datetime(
        readonly=True,
        help="Timestamp of last successful credential validation",
    )

    # ------------------------------------------------------------
    # CONSTRAINTS
    # ------------------------------------------------------------

    # System-wide credentials: name must be globally unique
    _credential_system_unique = models.UniqueIndex(
        "(name) WHERE company_id IS NULL AND active = true",
        "Active system-wide credential names must be unique!",
    )

    # Company-specific credentials: name must be unique per company
    _credential_company_unique = models.UniqueIndex(
        "(company_id, name) WHERE company_id IS NOT NULL AND active = true",
        "Active credential names must be unique per company!",
    )

    def _validate_required_fields_for_category(self):
        """Validate that required fields are filled based on credential category.

        This is called from create/write AFTER super() to ensure all inverse
        methods have completed and credential_value_encrypted is populated.

        Note: We don't use @api.constrains because during create/write the inverse
        methods for computed fields (bearer_token -> credential_data -> encrypted)
        may not have completed when constraints run.

        Supports two storage methods:
        1. Simple storage: direct field values (credential_value, username, etc.)
        2. JSON storage: computed fields stored via credential_data -> encrypted
        """
        # Invalidate once for the whole recordset (fields populated by inverse chain)
        self.invalidate_recordset(["credential_value_encrypted"])

        for record in self:
            if not record.category_code:
                continue

            config = CATEGORY_REQUIRED_FIELDS.get(record.category_code)
            if not config:
                continue  # No requirements for this category (e.g., 'custom')

            # Decrypt JSON blob once so we can verify specific keys are present
            # rather than trusting blob-existence as a proxy for field presence.
            json_data = {}
            encrypted = record.with_context(bin_size=False).credential_value_encrypted
            if encrypted:
                # JSON-parse errors are expected for simple-storage records
                # whose plaintext happens to land here during transitions, so
                # we swallow them and fall through to the per-field check.
                # Decryption errors (ValidationError from _decrypt_value) must
                # NOT be swallowed — reporting them as "missing fields" hid
                # the real cause in the previous implementation.
                decrypted = record._decrypt_value(encrypted)
                if decrypted:
                    try:
                        parsed = json.loads(decrypted)
                    except json.JSONDecodeError, ValueError:
                        parsed = {}
                    if isinstance(parsed, dict):
                        json_data = parsed

            missing_fields = []
            for spec in config["fields"]:
                # A spec is a single field name (str) or a tuple of
                # alternatives where any one satisfies the slot. Tuples
                # cover the simple-vs-JSON-accessor duality for
                # single-payload categories (see CATEGORY_REQUIRED_FIELDS
                # comment and t21134 F1b).
                alternatives = (spec,) if isinstance(spec, str) else tuple(spec)
                satisfied = False
                for field_name in alternatives:
                    # Simple-field storage path (direct column / accessor)
                    if getattr(record, field_name, None):
                        satisfied = True
                        break
                    # JSON storage path (field stored inside credential_value_encrypted)
                    if json_data.get(field_name):
                        satisfied = True
                        break
                if not satisfied:
                    # Report the first alternative so the user-facing
                    # message stays stable and predictable.
                    missing_fields.append(alternatives[0])

            if missing_fields:
                raise ValidationError(
                    self.env._("%(message)s\n\nMissing fields: %(fields)s")
                    % {
                        "message": config["message"],
                        "fields": ", ".join(missing_fields),
                    },
                )

    @api.constrains("notes")
    def _check_notes_for_secrets(self):
        """Warn (don't block) if notes appear to contain secrets.

        Notes are plain-text (the field's help text already says so). A hard
        ValidationError here blocks legitimate operational notes such as
        "rotate the old password: expired". Log a warning instead; the user
        stays informed without being locked out of saving.
        """
        for record in self:
            if not record.notes:
                continue
            # Identify WHICH pattern matched so we can log its name only.
            # SECURITY: never log match.group() — that is (or contains) the
            # secret value itself. Log the pattern label instead.
            matched_names = [
                name
                for name, regex in SECRET_NAMED_REGEXES
                if regex.search(record.notes)
            ]
            if not matched_names:
                continue
            _logger.warning(
                "Possible secret pattern in notes for credential %s: "
                "matched pattern(s) %s (value not logged).",
                record.id or "new",
                ", ".join(matched_names),
            )

    # ------------------------------------------------------------
    # CRUD METHODS
    # ------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to set encryption_key_version on new credentials.

        Also guards _PROTECTED_STATS_FIELDS the same way write() does, so a
        caller cannot seed a new record with fake usage_count / health_status
        / last_used_at values. Internal code that genuinely needs to set these
        (imports, data migrations) can pass the _INTERNAL_STATS_UPDATE_KEY
        context flag just like write().
        """
        # Protect statistics fields from being seeded at creation time.
        # Without this guard, write()'s protection is trivially bypassed by
        # issuing a create() instead.
        if not self.env.context.get(self._INTERNAL_STATS_UPDATE_KEY):
            for vals in vals_list:
                protected_being_set = vals.keys() & self._PROTECTED_STATS_FIELDS
                if protected_being_set:
                    raise ValidationError(
                        self.env._(
                            "Cannot seed protected statistics fields at creation!\n\n"
                            "The following fields are managed internally: %(fields)s\n\n"
                            "Create the credential first, then use the dedicated "
                            "methods (increment_usage, action_validate_credential, "
                            "mark_as_used) to update statistics.",
                        )
                        % {
                            "fields": ", ".join(sorted(protected_being_set)),
                        },
                    )

        # Protect storage_method from being seeded at creation time. It must
        # be sealed by an inverse method based on which payload field was
        # actually provided, not by the caller declaring their intent.
        if not self.env.context.get(self._INTERNAL_STORAGE_UPDATE_KEY):
            for vals in vals_list:
                if self._STORAGE_METHOD_GUARD_FIELD in vals:
                    raise ValidationError(
                        self.env._(
                            "storage_method cannot be set directly at creation. "
                            "It is sealed automatically by the first payload write "
                            "(credential_value -> 'simple', credential_data or any "
                            "JSON accessor -> 'json').",
                        ),
                    )

        # Get current encryption key version
        current_version = self._get_current_encryption_key_version() or 1

        for vals in vals_list:
            # Only set if not explicitly provided and credential will be encrypted
            if "encryption_key_version" not in vals:
                # Check if any encrypted field will be set
                has_encrypted_content = any(
                    vals.get(field)
                    for field in [
                        "credential_value",
                        "credential_data",
                        "certificate_content",
                        "certificate_password",
                        "private_key_content",
                        "username",
                        "password",
                        "api_key",
                        "api_secret",
                        "oauth_access_token",
                        "oauth_refresh_token",
                        "bearer_token",
                    ]
                )
                if has_encrypted_content:
                    vals["encryption_key_version"] = current_version

        records = super().create(vals_list)

        # Validate required fields AFTER super().create() to ensure all inverse
        # methods have completed (bearer_token -> credential_data -> encrypted)
        records._validate_required_fields_for_category()

        return records

    # Protected statistics fields - only modifiable via internal methods
    _PROTECTED_STATS_FIELDS = frozenset(
        {
            "usage_count",
            "success_count",
            "error_count",
            "cache_hits",
            "cache_misses",
            "health_status",
            "health_message",
            "last_health_check",
            "last_health_check_latency",
            "total_health_checks",
            "failed_health_checks",
            "last_used_at",
            "last_error",
            "last_error_date",
        }
    )

    # Context key to allow internal updates to protected fields
    _INTERNAL_STATS_UPDATE_KEY = "_credential_internal_stats_update"

    # Context key that authorizes an inverse method to seal storage_method
    # on its first payload write. Any write() that sets storage_method
    # without this key raises.
    _INTERNAL_STORAGE_UPDATE_KEY = "_credential_internal_storage_update"

    # Storage-mode payload fields. Writing any of these triggers the
    # write-once storage invariant. Used by the write() guard so a user
    # cannot sneak storage_method in alongside a legitimate field update.
    _STORAGE_METHOD_GUARD_FIELD = "storage_method"

    def write(self, vals):
        """Override write to protect statistics fields and set encryption version.

        Statistics fields are protected from external modification to ensure
        data integrity. Internal methods use a context flag to bypass this.
        storage_method is likewise protected: it is a write-once invariant
        sealed by the first payload inverse and cannot be set directly.
        """
        # Check for protected fields being modified externally
        if not self.env.context.get(self._INTERNAL_STATS_UPDATE_KEY):
            protected_being_modified = set(vals.keys()) & self._PROTECTED_STATS_FIELDS
            if protected_being_modified:
                raise ValidationError(
                    self.env._(
                        "Cannot modify protected statistics fields directly!\n\n"
                        "The following fields are managed internally: %(fields)s\n\n"
                        "Use the appropriate methods:\n"
                        "- increment_usage() for usage statistics\n"
                        "- action_validate_credential() for health checks\n"
                        "- mark_as_used() for last_used_at",
                    )
                    % {"fields": ", ".join(sorted(protected_being_modified))},
                )

        # Protect storage_method: only the internal inverse path may set it.
        if self._STORAGE_METHOD_GUARD_FIELD in vals and not self.env.context.get(
            self._INTERNAL_STORAGE_UPDATE_KEY,
        ):
            raise ValidationError(
                self.env._(
                    "storage_method is a write-once invariant managed by the "
                    "credential model. It is sealed on the first payload write "
                    "and cannot be modified directly. To change storage mode, "
                    "archive this credential and create a new one.",
                ),
            )

        # Fields that trigger encryption
        encrypted_fields = [
            "credential_value",
            "credential_data",
            "certificate_content",
            "certificate_password",
            "private_key_content",
            "username",
            "password",
            "api_key",
            "api_secret",
            "oauth_access_token",
            "oauth_refresh_token",
            "bearer_token",
        ]

        # Check if any encrypted field is being set
        adding_encrypted_content = any(vals.get(field) for field in encrypted_fields)

        if adding_encrypted_content:
            # Update records that don't have encryption_key_version set
            current_version = self._get_current_encryption_key_version() or 1

            for record in self:
                if not record.encryption_key_version:
                    # Set version for this record only (use SQL to avoid recursion)
                    self.env.cr.execute(
                        """
                        UPDATE credential_credential
                        SET encryption_key_version = %s
                        WHERE id = %s AND (encryption_key_version IS NULL
                                           OR encryption_key_version = 0)
                        """,
                        [current_version, record.id],
                    )

        result = super().write(vals)

        # Validate required fields if category or credential fields changed
        category_changed = "category_id" in vals
        if category_changed or adding_encrypted_content:
            self._validate_required_fields_for_category()

        return result

    def unlink(self):
        """Audit credential deletion before the rows disappear.

        Emits a ``delete`` access-log entry per credential out-of-band (fresh
        RW cursor, committed independently) BEFORE the ORM delete runs. This
        is the only emitter of the ``delete`` operation and it must happen
        out-of-band: the access-log FK is ``ondelete=set null``, and the log
        write has to survive the credential row vanishing. The denormalized
        credential_name captured in the row keeps the entry readable
        afterwards. A failed audit write never blocks the deletion.
        """
        for record in self:
            if not record.id:
                continue
            try:
                record._log_access_out_of_band("delete")
            except Exception as e:
                _logger.warning(
                    "Failed to write delete audit log for credential %s: %s",
                    record.id,
                    e,
                )
        return super().unlink()

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    @api.depends("name", "company_id", "category_id")
    def _compute_display_name(self):
        """Compute display name with category and company context."""
        for record in self:
            parts = [record.name or ""]
            if record.category_id:
                parts.append(f"[{record.category_id.name}]")
            if record.company_id:
                parts.append(f"({record.company_id.name})")
            else:
                parts.append("(System-wide)")
            record.display_name = " ".join(parts)

    @api.depends("company_id")
    def _compute_is_system_wide(self):
        """Determine if this is a system-wide credential (no company assigned)."""
        for record in self:
            record.is_system_wide = not record.company_id

    def _parse_certificate(self):
        """Parse certificate content and return cert object, private key, and format.

        Returns:
            tuple: (cert, private_key, format_str, error_msg)
                - cert: x509 certificate object or None
                - private_key: private key object or None (from PKCS12)
                - format_str: 'der', 'pem', 'pkcs12', or None
                - error_msg: error message string or empty string

        """
        self.ensure_one()
        content = self.with_context(bin_size=False).certificate_content

        if not content:
            return None, None, None, ""

        content = base64.b64decode(content)
        cert = None
        private_key = None
        format_str = None
        password = (
            self.certificate_password.encode("utf-8")
            if self.certificate_password
            else None
        )

        # Try DER format
        try:
            cert = x509.load_der_x509_certificate(content)
            format_str = "der"
        except ValueError:
            pass

        # Try PKCS12 format
        if not cert:
            try:
                private_key, cert, _additional_certs = pkcs12.load_key_and_certificates(
                    content, password
                )
                format_str = "pkcs12"
            except ValueError:
                pass

        # Try PEM format
        if not cert:
            try:
                cert = x509.load_pem_x509_certificate(content)
                format_str = "pem"
            except ValueError:
                pass

        if not cert:
            return (
                None,
                None,
                None,
                self.env._(
                    "Could not load certificate. Check content or password.",
                ),
            )

        return cert, private_key, format_str, ""

    @api.depends(
        "certificate_content_encrypted",
        "certificate_password_encrypted",
    )
    def _compute_certificate_data(self):
        """Parse certificate and extract stored metadata fields only.

        Preserves last-known-good metadata on parse failure. If the user
        uploads a bad cert (or enters the wrong PKCS12 password for a
        previously valid cert), we keep the stored subject/serial/dates
        and only surface certificate_loading_error. Without this, a typo
        in the password blanks all visible cert state, which is indistin-
        guishable from "no cert loaded" in the UI.
        """
        for record in self:
            cert, _private_key, format_str, error_msg = record._parse_certificate()

            if error_msg:
                # Parse failed. Keep previously stored metadata (if any) so
                # the user can still see what was there before the bad edit.
                # Re-assigning the current value is a no-op to the ORM but
                # makes intent explicit.
                record.certificate_loading_error = error_msg
                record.certificate_format = record.certificate_format
                record.certificate_subject = record.certificate_subject
                record.certificate_serial = record.certificate_serial
                record.certificate_date_start = record.certificate_date_start
                record.certificate_date_end = record.certificate_date_end
                continue

            if not cert:
                # No content at all (uploaded cert was cleared). Legitimate
                # blank state — wipe metadata to match.
                record.certificate_format = None
                record.certificate_subject = None
                record.certificate_serial = None
                record.certificate_date_start = None
                record.certificate_date_end = None
                record.certificate_loading_error = ""
                continue

            # Extract certificate metadata (stored fields only)
            record.certificate_loading_error = ""
            record.certificate_format = format_str
            record.certificate_serial = str(cert.serial_number)

            try:
                common_name = cert.subject.get_attributes_for_oid(
                    x509.NameOID.COMMON_NAME,
                )
                record.certificate_subject = common_name[0].value if common_name else ""
            except ValueError:
                record.certificate_subject = None

            # cryptography >= 42 is the minimum supported on Odoo 19 / Py3.14,
            # so the legacy not_valid_before / not_valid_after accessors are
            # gone — always read the UTC-aware variants and strip tzinfo.
            record.certificate_date_start = cert.not_valid_before_utc.replace(
                tzinfo=None,
            )
            record.certificate_date_end = cert.not_valid_after_utc.replace(
                tzinfo=None,
            )

    @api.depends("certificate_content_encrypted", "certificate_password_encrypted")
    def _compute_certificate_pem(self):
        """Compute certificate PEM (non-stored, on-demand)."""
        for record in self:
            cert, _private_key, _format_str, _error_msg = record._parse_certificate()
            if cert:
                record.certificate_pem = base64.b64encode(
                    cert.public_bytes(Encoding.PEM)
                )
            else:
                record.certificate_pem = None

    @api.depends(
        "certificate_content_encrypted",
        "certificate_password_encrypted",
        "private_key_content_encrypted",
    )
    def _compute_private_key_pem(self):
        """Compute private key PEM (non-stored, on-demand).

        SECURITY: producing the private key PEM is a genuine plaintext-access
        event (the crown-jewel secret). Every record that actually yields key
        material is rate-limited and audited as a 'use' at this single
        private-key choke point — unless called on an internal path
        (``_credential_internal_access`` context, set by ``_sign`` which does
        its own single enforcement to avoid double counting).

        This field is store=False and is never eagerly recomputed by the
        encryption-key migration (which re-encrypts ciphertext directly via the
        mixin, without reading private_key_pem), so re-encryption paths do not
        trip the rate limiter / audit log.
        """
        internal = self.env.context.get("_credential_internal_access")
        for record in self:
            _cert, private_key, _format_str, _error_msg = record._parse_certificate()
            password = (
                record.certificate_password.encode("utf-8")
                if record.certificate_password
                else None
            )

            pk_pem = None
            # Handle private key from PKCS12
            if private_key:
                pk_pem = base64.b64encode(
                    private_key.private_bytes(
                        encoding=Encoding.PEM,
                        format=serialization.PrivateFormat.PKCS8,
                        encryption_algorithm=serialization.NoEncryption(),
                    ),
                )
            elif record.private_key_content:
                # Try to load separately uploaded private key
                try:
                    pk_content = base64.b64decode(
                        record.with_context(bin_size=False).private_key_content,
                    )
                    pk = None
                    try:
                        pk = serialization.load_pem_private_key(pk_content, password)
                    except ValueError, TypeError:
                        with contextlib.suppress(ValueError, TypeError):
                            pk = serialization.load_der_private_key(
                                pk_content,
                                password,
                            )
                    if pk:
                        pk_pem = base64.b64encode(
                            pk.private_bytes(
                                encoding=Encoding.PEM,
                                format=serialization.PrivateFormat.PKCS8,
                                encryption_algorithm=serialization.NoEncryption(),
                            ),
                        )
                except Exception as e:
                    _logger.warning(
                        "Failed to load private key for credential %s: %s",
                        record.id or "new",
                        e,
                    )

            # Rate-limit + audit only when we are actually exposing key
            # material to an external caller. Enforcement (may raise) happens
            # before the value is assigned/exposed.
            if pk_pem and record.id and not internal:
                record._enforce_access_rate_limit()
                record._log_access_guarded("use")

            record.private_key_pem = pk_pem

    @api.depends(
        "certificate_date_start",
        "certificate_date_end",
        "certificate_loading_error",
    )
    def _compute_certificate_is_valid(self):
        """Check if certificate is currently valid."""
        now = fields.Datetime.now()
        for record in self:
            if (
                not record.certificate_date_start
                or not record.certificate_date_end
                or record.certificate_loading_error
            ):
                record.certificate_is_valid = False
            else:
                record.certificate_is_valid = (
                    record.certificate_date_start <= now <= record.certificate_date_end
                )

    @api.depends("certificate_password_encrypted")
    def _compute_certificate_password(self):
        """Decrypt certificate password for use."""
        self._compute_encrypted_char_field(
            "certificate_password_encrypted",
            "certificate_password",
        )

    @api.depends("certificate_content_encrypted")
    def _compute_certificate_content(self):
        """Decrypt certificate content for use.

        Security: Certificate files (especially PKCS12) may contain private keys
        and must be stored encrypted.
        """
        self._compute_encrypted_binary_field(
            "certificate_content_encrypted",
            "certificate_content",
        )

    @api.depends("private_key_content_encrypted")
    def _compute_private_key_content(self):
        """Decrypt private key content for use."""
        self._compute_encrypted_binary_field(
            "private_key_content_encrypted",
            "private_key_content",
        )

    @api.depends("credential_value_encrypted")
    def _compute_cached_plaintext(self):
        """Decrypt credential_value_encrypted once per transaction.

        This is the SINGLE audit point for plaintext access. All downstream
        plaintext-derived computes (credential_value, credential_data,
        storage_method, and every JSON accessor like api_key/password/etc.)
        depend on this field, and Odoo's compute cache memoizes the result
        per (record, transaction). So a form open that reads seven JSON
        accessor fields triggers exactly one Fernet.decrypt AND exactly one
        credential.access.log entry per credential — not seven, not zero.

        List views do not read plaintext-derived fields, so opening a
        500-row credential list triggers zero decryptions and zero audit
        entries.

        Decrypt failures (missing key, bad ciphertext) are logged to the
        Python logger only — they do not produce a successful-read audit
        entry, because no plaintext was exposed. See S2 in the investigation
        notes.
        """
        for record in self:
            encrypted = record.with_context(bin_size=False).credential_value_encrypted
            if not encrypted:
                record.cached_plaintext = False
                continue

            try:
                decrypted = record._decrypt_value_safe(encrypted, default=None)
            except Exception as e:
                _logger.warning(
                    "Credential %s: decrypt failed in _compute_cached_plaintext: %s",
                    record.id or "new",
                    e,
                )
                record.cached_plaintext = False
                continue

            if decrypted is None:
                _logger.warning(
                    "Credential %s: could not decrypt credential_value_encrypted "
                    "(key missing or rotated). Field will read as empty.",
                    record.id or "new",
                )
                record.cached_plaintext = False
                continue

            # Rate-limit genuine plaintext access at this single decrypt choke
            # point, BEFORE exposing the plaintext. Covers credential_value and
            # every JSON accessor (api_key/password/...), all of which derive
            # from cached_plaintext. Raises ValidationError (denies) if the
            # per-user cap is exceeded — this must NOT be swallowed.
            if decrypted and record.id:
                record._enforce_access_rate_limit()

            record.cached_plaintext = decrypted or False

            # Emit one audit entry per successful decryption. Because this
            # compute is memoized by the ORM for the whole transaction, this
            # produces one entry per (record, transaction) — naturally
            # deduplicated. A failing audit-log write must never break a
            # credential read — EXCEPT a readonly-transaction signal, which
            # drives Odoo 19's RW retry and must propagate (handled by
            # _log_access_guarded routing readonly writes out-of-band).
            if decrypted and record.id:
                try:
                    record._log_access_guarded("read")
                except psycopg_errors.ReadOnlySqlTransaction:
                    raise
                except Exception as e:
                    _logger.warning(
                        "Credential %s: failed to write audit log for read: %s",
                        record.id,
                        e,
                    )

    @api.depends("cached_plaintext", "storage_method")
    def _compute_credential_value(self):
        """Expose the decrypted plaintext as credential_value.

        Only surfaces the plaintext for simple-storage records. Any other
        storage_method (none, json) returns False so a JSON credential
        can never leak its JSON blob through the simple-value accessor.
        This is the read-side half of the write-once storage invariant.
        """
        for record in self:
            if record.storage_method != "simple":
                record.credential_value = False
                continue
            record.credential_value = record.cached_plaintext or False

    @api.depends("cached_plaintext", "storage_method")
    def _compute_credential_data(self):
        """Expose the decrypted plaintext as credential_data for JSON records.

        Only surfaces the plaintext for json-storage records. Simple and
        none storage return "{}" so the JSON-accessor computes
        short-circuit cleanly and we never round-trip a simple value
        through the JSON path.
        """
        for record in self:
            if record.storage_method != "json":
                record.credential_data = "{}"
                continue
            plaintext = record.cached_plaintext
            if not plaintext:
                record.credential_data = "{}"
                continue
            try:
                json.loads(plaintext)
                record.credential_data = plaintext
            except json.JSONDecodeError, ValueError:
                # Storage says json but payload does not parse. Surface as
                # empty rather than leaking a non-JSON string through the
                # JSON accessor.
                record.credential_data = "{}"

    # _compute_storage_method was removed in 19.0.1.0.1. storage_method is
    # now a write-once stored field set by inverse methods, not inferred from
    # the plaintext. Inferring-from-serialized-data was the root cause of the
    # simple->JSON silent-mutation bug: a credential whose simple value
    # happened to parse as JSON would flip modes mid-read. Authoritative
    # state avoids that entire class of bug.

    @api.depends("date_expiration")
    def _compute_is_expired(self):
        """Determine if credential has expired based on date_expiration date."""
        now = fields.Datetime.now()
        for record in self:
            record.is_expired = bool(
                record.date_expiration and record.date_expiration < now
            )

    @api.depends("date_expiration")
    def _compute_days_until_expiry(self):
        """Calculate days remaining until credential expiration."""
        now = fields.Datetime.now()
        for record in self:
            if record.date_expiration:
                delta = record.date_expiration - now
                record.days_until_expiry = delta.days
            else:
                record.days_until_expiry = self.DAYS_NO_EXPIRY

    @api.depends("success_count", "error_count")
    def _compute_success_rate(self):
        """Calculate success rate percentage from usage statistics."""
        for record in self:
            total = record.success_count + record.error_count
            if total > 0:
                record.success_rate = (record.success_count / total) * 100
            else:
                record.success_rate = 0.0

    @api.depends("total_health_checks", "failed_health_checks")
    def _compute_health_check_success_rate(self):
        """Calculate health check success rate percentage."""
        for record in self:
            if record.total_health_checks > 0:
                success = record.total_health_checks - record.failed_health_checks
                record.health_check_success_rate = (
                    success / record.total_health_checks
                ) * 100
            else:
                record.health_check_success_rate = 0.0

    _JSON_ACCESSOR_FIELDS = (
        "api_key",
        "api_secret",
        "bearer_token",
        "username",
        "password",
        "oauth_access_token",
        "oauth_refresh_token",
    )

    @api.depends("credential_data")
    def _compute_credential_accessors(self) -> None:
        """Populate every JSON accessor field with a single parse per record.

        Previously each accessor had its own compute calling json.loads on
        credential_data independently — seven accessors on a form open meant
        seven parses of the same string per record. Sharing one compute
        method lets Odoo invoke us once per record per transaction and then
        serve every accessor from the field cache.
        """
        for record in self:
            data = record.credential_data
            parsed: dict[str, Any] = {}
            if data and data != "{}":
                try:
                    loaded = json.loads(data)
                    if isinstance(loaded, dict):
                        parsed = loaded
                except (json.JSONDecodeError, ValueError, TypeError) as e:
                    _logger.debug(
                        "Could not parse credential_data for %s: %s",
                        record.id or "new",
                        e,
                    )
            for field_name in self._JSON_ACCESSOR_FIELDS:
                record[field_name] = parsed.get(field_name, False)

    # Credential Hash
    @api.depends("credential_value_encrypted")
    def _compute_credential_hash(self) -> None:
        """Compute hash of encrypted credentials for cache key generation.

        Security Note:
            This hash is computed from the ENCRYPTED value, not the plaintext.
            Since Fernet encryption uses a random 128-bit IV for each operation,
            two encryptions of the same plaintext produce different ciphertext.
            This means:
            - The hash does NOT reveal the plaintext credential
            - The hash does NOT allow comparison between credentials
            - Two credentials with identical plaintext will have different hashes
            - Only re-encrypting the same record produces identical encrypted bytes

        Usage:
            Used by api_gateway for session cache keys: {service}:{company}:{hash}
            When credentials change, the hash changes, invalidating cached sessions.
        """
        for cred in self:
            if cred.credential_value_encrypted:
                # Binary fields can return str or bytes
                encrypted = cred.credential_value_encrypted
                if isinstance(encrypted, str):
                    encrypted = encrypted.encode("utf-8")
                cred.credential_hash = hashlib.sha256(encrypted).hexdigest()
            else:
                cred.credential_hash = False

    # ------------------------------------------------------------
    # INVERSE METHODS
    # ------------------------------------------------------------

    def _seal_storage_method(self, target_mode: str) -> None:
        """Seal storage_method on first payload write; raise on mode conflict.

        Target mode must be 'simple' or 'json'. If the record is still in
        the default 'none' state, this transitions it to target_mode. If
        it is already in target_mode, this is a no-op. Any attempt to
        cross from simple->json or json->simple raises ValidationError,
        which is the whole point of option D: mixing storage modes on a
        single record is forbidden.
        """
        self.ensure_one()
        current = self.storage_method or "none"
        if current == target_mode:
            return
        if current != "none":
            raise ValidationError(
                self.env._(
                    "This credential is already using %(current)s storage. "
                    "Writing through the %(target)s path would silently "
                    "corrupt the stored value. Archive this credential and "
                    "create a new one if you need to change storage mode.",
                )
                % {"current": current, "target": target_mode},
            )
        # Seal the invariant through the internal write path. We go through
        # write() rather than a direct SQL update so ORM caches and
        # dependent computes (credential_value, credential_data) stay in
        # sync; the internal context key satisfies the write() guard.
        self.with_context(
            **{self._INTERNAL_STORAGE_UPDATE_KEY: True},
        ).write({self._STORAGE_METHOD_GUARD_FIELD: target_mode})

    def _inverse_credential_value(self):
        """Encrypt credential value when set.

        Security validation:
        - Maximum size: 8KB (prevents DoS via large payloads)

        Storage invariant: this path seals the record to 'simple' storage
        on first write. Attempting to write credential_value on a record
        already sealed as 'json' raises ValidationError.
        """
        for record in self:
            if record.credential_value:
                # Security: Check size limit
                value_size = len(record.credential_value.encode("utf-8"))
                if value_size > MAX_CREDENTIAL_VALUE_SIZE:
                    raise ValidationError(
                        self.env._(
                            "Credential value exceeds maximum size!\n\n"
                            "Size: %(size)s bytes\n"
                            "Maximum: %(max)s bytes (8KB)\n\n"
                            "For larger data, use credential_data (JSON format, up to 64KB).",
                        )
                        % {
                            "size": value_size,
                            "max": MAX_CREDENTIAL_VALUE_SIZE,
                        },
                    )

                record._seal_storage_method("simple")
                record.credential_value_encrypted = record._encrypt_value(
                    record.credential_value,
                )
            elif record.storage_method == "simple":
                # Clearing a sealed simple credential wipes the ciphertext
                # but leaves the mode sealed; we do not let callers
                # transition back to 'none' and then into 'json'.
                record.credential_value_encrypted = False

    def _inverse_credential_data(self):
        """Validate and encrypt JSON credential data.

        Security validations:
        - Maximum size: 64KB (prevents DoS via large payloads)
        - Maximum nesting depth: 10 levels (prevents stack overflow)
        - Valid JSON syntax

        Storage invariant: seals the record to 'json' storage on first
        write. Attempting to write credential_data on a 'simple' record
        raises ValidationError.
        """
        for record in self:
            if not record.credential_data or record.credential_data == "{}":
                if record.storage_method == "json":
                    record.credential_value_encrypted = False
                continue
            record._seal_storage_method("json")

            # Security: Check size limit
            data_size = len(record.credential_data.encode("utf-8"))
            if data_size > MAX_CREDENTIAL_DATA_SIZE:
                raise ValidationError(
                    self.env._(
                        "Credential data exceeds maximum size!\n\nSize: %(size)s bytes\nMaximum: %(max)s bytes (64KB)",
                    )
                    % {"size": data_size, "max": MAX_CREDENTIAL_DATA_SIZE},
                )

            try:
                parsed_data = json.loads(record.credential_data)
            except (json.JSONDecodeError, ValueError) as e:
                raise ValidationError(
                    self.env._("Invalid JSON format in credential_data!\nError: %s")
                    % str(e),
                ) from e

            # Security: Check nesting depth
            try:
                _check_json_depth(parsed_data)
            except ValueError as e:
                raise ValidationError(
                    self.env._(
                        "Invalid JSON structure!\n\nError: %(error)s\nMaximum nesting depth allowed: %(max)s levels",
                    )
                    % {"error": str(e), "max": MAX_JSON_NESTING_DEPTH},
                ) from e

            record.credential_value_encrypted = record._encrypt_value(
                record.credential_data,
            )

    def _inverse_credential_json_field(self, field_name: str) -> None:
        """Generic inverse method for JSON-stored credential fields.

        Storage invariant: seals the record to 'json' storage on first
        write. Writing any JSON accessor (api_key, bearer_token,
        username, password, oauth_access_token, oauth_refresh_token,
        api_secret) on a 'simple' record raises ValidationError.

        We read the existing dict via _read_credential_dict_raw rather
        than get_credential_dict() because the latter is rate-limited
        and audit-logged as a user-facing read; this internal merge
        step should not count against either.
        """
        for record in self:
            value = getattr(record, field_name)
            if not value and record.storage_method != "json":
                # Clearing an accessor on a non-json record is a no-op;
                # there is no JSON blob to remove the key from.
                continue
            record._seal_storage_method("json")
            data = record._read_credential_dict_raw()
            if value:
                data[field_name] = value
            else:
                data.pop(field_name, None)
            record.set_credential_dict(data)

    def _read_credential_dict_raw(self) -> dict:
        """Internal: read the decrypted JSON dict without rate limiting.

        Only valid for records already sealed as 'json' storage. For
        'none' records (first-write case) returns an empty dict so the
        inverse path can build up the initial payload. Never falls
        back to wrapping credential_value under a 'value' key: that
        was the source of the simple->JSON silent-mutation bug.
        """
        self.ensure_one()
        if self.storage_method != "json":
            return {}
        # Lock this credential row for the read-merge-re-encrypt below.
        # Concurrent JSON-accessor writes (e.g. one txn setting api_key and
        # another setting oauth_access_token) each do read-merge-re-encrypt of
        # the SAME credential_value_encrypted blob; without a row lock the
        # second writer's read can predate the first writer's commit and the
        # merge silently drops the first key. FOR NO KEY UPDATE serializes them
        # (we only UPDATE non-key columns) while still allowing FK references.
        if self.id:
            self.env.cr.execute(
                "SELECT id FROM credential_credential WHERE id = %s "
                "FOR NO KEY UPDATE",
                [self.id],
            )
            # Drop any pre-lock cached ciphertext so we re-read the value the
            # lock now guarantees is the latest committed blob.
            self.invalidate_recordset(["credential_value_encrypted"])
        encrypted = self.with_context(bin_size=False).credential_value_encrypted
        if not encrypted:
            return {}
        plaintext = self._decrypt_value_safe(encrypted, default=None)
        if not plaintext:
            return {}
        try:
            parsed = json.loads(plaintext)
        except json.JSONDecodeError, ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _inverse_credential_field_api_key(self) -> None:
        """Store api_key in JSON credential data."""
        self._inverse_credential_json_field("api_key")

    def _inverse_credential_field_api_secret(self) -> None:
        """Store api_secret in JSON credential data."""
        self._inverse_credential_json_field("api_secret")

    def _inverse_credential_field_username(self) -> None:
        """Store username in JSON credential data."""
        self._inverse_credential_json_field("username")

    def _inverse_credential_field_password(self) -> None:
        """Store password in JSON credential data."""
        self._inverse_credential_json_field("password")

    def _inverse_credential_field_oauth_access_token(self) -> None:
        """Store oauth_access_token in JSON credential data."""
        self._inverse_credential_json_field("oauth_access_token")

    def _inverse_credential_field_oauth_refresh_token(self) -> None:
        """Store oauth_refresh_token in JSON credential data."""
        self._inverse_credential_json_field("oauth_refresh_token")

    def _inverse_certificate_password(self):
        """Encrypt certificate password when set."""
        self._inverse_encrypted_char_field(
            "certificate_password",
            "certificate_password_encrypted",
        )

    def _inverse_certificate_content(self):
        """Encrypt certificate content when uploaded.

        Security: PKCS12 files contain private keys and must be encrypted at rest.
        """
        self._inverse_encrypted_binary_field(
            "certificate_content",
            "certificate_content_encrypted",
        )

    def _inverse_private_key_content(self):
        """Encrypt private key content when uploaded."""
        self._inverse_encrypted_binary_field(
            "private_key_content",
            "private_key_content_encrypted",
        )

    def _inverse_credential_field_bearer_token(self) -> None:
        """Store bearer_token in JSON credential data."""
        self._inverse_credential_json_field("bearer_token")

    # ------------------------------------------------------------
    # ONCHANGE METHODS
    # ------------------------------------------------------------

    @api.onchange("category_id")
    def _onchange_category_id(self):
        """Apply default settings from category when category changes.

        This is UI convenience - sets defaults when user selects a category.
        Users can still override these values after selection.
        """
        if self.category_id:
            self.enable_rate_limiting = self.category_id.default_enable_rate_limiting
            self.rate_limit_max_attempts = (
                self.category_id.default_rate_limit_max_attempts
            )
            self.auto_validate_health = self.category_id.default_auto_validate_health
            self.allow_key_fallback = self.category_id.default_allow_key_fallback

    # ------------------------------------------------------------
    # ACTION METHODS
    # ------------------------------------------------------------

    # Tuples: char_field_on_plaintext_compute, encrypted_binary_storage, is_binary.
    # Single source of truth for every Fernet-encrypted column on this model.
    # Anything here is re-encrypted by action_migrate_encryption_keys. Add new
    # encrypted fields to this list, not as ad-hoc writes in the action.
    _ENCRYPTED_FIELD_PAIRS = (
        ("credential_value", "credential_value_encrypted", False),
        ("certificate_content", "certificate_content_encrypted", True),
        ("certificate_password", "certificate_password_encrypted", False),
        ("private_key_content", "private_key_content_encrypted", True),
    )

    def action_migrate_encryption_keys(self) -> dict[str, Any]:
        """Re-encrypt every encrypted field on every credential with the current key.

        Previously this method only touched credential_value_encrypted, which
        meant that after rotating ODOO_API_ENCRYPTION_KEY and retiring the old
        V1 env var, any certificate/PKCS12 credential became permanently
        undecryptable. It now walks _ENCRYPTED_FIELD_PAIRS and re-encrypts
        every column, using a per-record SAVEPOINT so one bad row doesn't
        abort the batch.

        Runs under sudo() so admins with restricted allowed_company_ids don't
        silently skip credentials of other companies — the migration is a
        system-wide operation, authorization is enforced by the admin-group
        check above, not by the record rule.
        """
        if not self.env.user.has_group(
            "base_credential_manager.group_credential_admin",
        ):
            raise UserError(
                self.env._(
                    "Only Credential Manager administrators can migrate encryption keys."
                ),
            )
        self.check_access("write")

        current_version = self._get_current_encryption_key_version()

        # Skip credentials already encrypted with the current key. An admin
        # re-running this action after a successful migration should be a
        # no-op, not an N-record re-encrypt cycle. encryption_key_version
        # defaults to 0 for legacy/untracked records, so "< current_version"
        # naturally includes them.
        eligible = self.sudo().search(
            [("encryption_key_version", "<", current_version)],
        )
        total_eligible = len(eligible)
        total_all = self.sudo().search_count([])
        skipped = total_all - total_eligible
        migrated = 0
        failed = 0
        errors = []

        _logger.info(
            "Starting encryption key migration: %d eligible / %d total "
            "credentials (%d already at key version %d)",
            total_eligible,
            total_all,
            skipped,
            current_version,
        )

        for cred in eligible:
            savepoint = f"cred_migrate_{cred.id}"
            self.env.cr.execute(f"SAVEPOINT {savepoint}")
            try:
                touched = False
                for _plain_field, enc_field, is_binary in self._ENCRYPTED_FIELD_PAIRS:
                    encrypted = cred.with_context(bin_size=False)[enc_field]
                    if not encrypted:
                        continue
                    if is_binary:
                        plaintext_b64 = cred._decrypt_binary_value(encrypted)
                        if not plaintext_b64:
                            continue
                        # _decrypt_binary_value returns base64-encoded bytes,
                        # and _encrypt_binary_value expects the same shape.
                        cred[enc_field] = cred._encrypt_binary_value(plaintext_b64)
                    else:
                        plaintext = cred._decrypt_value(encrypted)
                        if not plaintext:
                            continue
                        cred[enc_field] = cred._encrypt_value(plaintext)
                    touched = True

                if touched:
                    cred.encryption_key_version = current_version
                    migrated += 1
                    _logger.debug(
                        "Migrated credential: %s (ID: %s)",
                        cred.name,
                        cred.id,
                    )
                self.env.cr.execute(f"RELEASE SAVEPOINT {savepoint}")
            except Exception as e:
                self.env.cr.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                failed += 1
                error_msg = f"Credential '{cred.name}' (ID: {cred.id}): {e!s}"
                errors.append(error_msg)
                _logger.error("Failed to migrate credential: %s", error_msg)

        _logger.info(
            "Encryption key migration complete: %d migrated, %d failed, "
            "%d skipped (already at key version %d)",
            migrated,
            failed,
            skipped,
            current_version,
        )

        return {
            "total": total_all,
            "eligible": total_eligible,
            "skipped": skipped,
            "migrated": migrated,
            "failed": failed,
            "errors": errors,
            "current_key_version": current_version,
        }

    def action_test_encryption_keys(self) -> dict[str, Any]:
        """Test decryption of the selected credentials with available keys.

        Operates on ``self``. The form-header button that binds this method
        passes the current record, so a user clicking "Test Decryption" on a
        single credential probes *that* credential — the previous behaviour
        of silently scanning every row in the table on a tooltip that said
        "this credential" was a side-channel trap for admins.

        Called on an empty recordset, the method still returns a zero-row
        result dict rather than falling back to a global scan; operators
        who genuinely want "test every credential" can select all in the
        list view and invoke the action from the menu.
        """
        if not self.env.user.has_group(
            "base_credential_manager.group_credential_admin",
        ):
            raise UserError(
                self.env._(
                    "Only Credential Manager administrators can test encryption keys."
                ),
            )
        credentials = self
        total = len(credentials)

        results = {
            "total": total,
            "current_key": 0,
            "old_keys": 0,
            "failed": 0,
            "details": [],
        }

        current_version = self._get_current_encryption_key_version()

        for cred in credentials:
            try:
                if not cred.credential_value_encrypted:
                    continue

                # Binary fields can return str or bytes
                encrypted = cred.credential_value_encrypted
                if isinstance(encrypted, str):
                    encrypted = encrypted.encode("utf-8")

                try:
                    cipher = Fernet(cred._get_encryption_key())
                    cipher.decrypt(encrypted)
                    results["current_key"] += 1
                    results["details"].append(
                        {
                            "name": cred.name,
                            "id": cred.id,
                            "key_version": "current",
                        },
                    )
                    continue
                except InvalidToken:
                    pass

                found = False
                for version in range(1, current_version) if current_version else []:
                    try:
                        old_key = cred._get_encryption_key(version=version)
                        if old_key:
                            cipher = Fernet(old_key)
                            cipher.decrypt(encrypted)
                            results["old_keys"] += 1
                            results["details"].append(
                                {
                                    "name": cred.name,
                                    "id": cred.id,
                                    "key_version": f"v{version}",
                                },
                            )
                            found = True
                            break
                    except Exception:
                        _logger.debug(
                            "Key version %s did not decrypt credential %s",
                            version,
                            cred.id,
                            exc_info=True,
                        )
                        continue

                if not found:
                    results["failed"] += 1
                    results["details"].append(
                        {
                            "name": cred.name,
                            "id": cred.id,
                            "key_version": "FAILED",
                        },
                    )

            except Exception as e:
                results["failed"] += 1
                _logger.error("Test failed for credential %s: %s", cred.name, e)

        return results

    def action_validate_credential(self) -> dict[str, Any]:
        """Validate credential by calling appropriate validation method.

        For certificate credentials, validates certificate is valid.
        Override in inheriting models for service-specific validation.
        """
        self.ensure_one()

        _logger.info(
            "Validating credential %s (category: %s)",
            self.name,
            self.category_code,
        )

        # Certificate-specific validation is the only built-in check. For any
        # other category, we have nothing to validate against here — inheriting
        # modules override this method to add service-specific probes. Stamping
        # 'healthy' on an unprobed credential is misleading, so we leave
        # health_status at 'unknown' and return a clearly-labeled result.
        if self.category_code == "certificate":
            if self.certificate_loading_error:
                result = {
                    "success": False,
                    "error": self.certificate_loading_error,
                }
            elif not self.certificate_is_valid:
                result = {
                    "success": False,
                    "error": self.env._("Certificate is expired or not yet valid"),
                }
            elif not self.private_key_pem:
                result = {
                    "success": False,
                    "error": self.env._("No private key available for signing"),
                }
            else:
                result = {
                    "success": True,
                    "message": self.env._("Certificate is valid until %s")
                    % self.certificate_date_end,
                }
            new_status = "healthy" if result["success"] else "error"
        else:
            result = {
                "success": False,
                "not_implemented": True,
                "message": self.env._(
                    "No built-in validation for category '%s'. "
                    "Override action_validate_credential in an inheriting "
                    "module to add a service-specific probe."
                )
                % (self.category_code or "unknown"),
            }
            new_status = "unknown"

        self.with_context(**{self._INTERNAL_STATS_UPDATE_KEY: True}).write(
            {
                "health_status": new_status,
                "health_message": result.get("message") or result.get("error", ""),
                "last_health_check": fields.Datetime.now(),
            },
        )

        return result

    # ------------------------------------------------------------
    # CRON METHODS
    # ------------------------------------------------------------

    @api.model
    def cron_validate_credentials(self):
        """Scheduled action to validate credentials with auto_validate_health enabled."""
        credentials = self.search(
            [
                ("auto_validate_health", "=", True),
                ("active", "=", True),
            ],
        )

        total = len(credentials)
        healthy = 0
        errors = 0
        skipped = 0

        _logger.info("Starting automated health validation for %d credentials", total)

        for cred in credentials:
            try:
                result = cred.action_validate_credential()
                if result.get("not_implemented"):
                    skipped += 1
                elif result.get("success"):
                    healthy += 1
                else:
                    errors += 1
            except Exception as e:
                errors += 1
                _logger.error(
                    "Automated health check failed for credential %s: %s",
                    cred.name,
                    e,
                )

        _logger.info(
            "Automated health validation complete: %d healthy, %d errors, "
            "%d skipped (no built-in validator) out of %d",
            healthy,
            errors,
            skipped,
            total,
        )

        return {
            "total": total,
            "healthy": healthy,
            "errors": errors,
            "skipped": skipped,
        }

    def cron_cleanup_rate_limiter(self):
        """Scheduled action to cleanup old rate limiter entries.

        Prevents memory bloat from the in-memory rate limiter by removing
        entries older than 24 hours.
        """
        limiter = get_credential_rate_limiter(self.env)
        cleaned = limiter.cleanup_old_entries(max_age_hours=24)
        stats = limiter.get_stats()

        _logger.info(
            "Rate limiter cleanup complete: removed %d keys, tracking %d active keys with %d total attempts",
            cleaned,
            stats["total_keys"],
            stats["total_attempts_tracked"],
        )

        return {
            "cleaned": cleaned,
            "active_keys": stats["total_keys"],
            "total_attempts": stats["total_attempts_tracked"],
        }

    # ------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------

    def _format_bytes(self, data, formatting="encodebytes"):
        """Format binary data according to requested format."""
        if formatting == "encodebytes":
            return base64.encodebytes(data)
        if formatting == "base64":
            return base64.b64encode(data)
        return data

    def _get_certificate_der_bytes(self, formatting="encodebytes"):
        """Get the DER bytes of the certificate.

        Args:
            formatting: 'encodebytes' (base64 with newlines), 'base64' (raw), or 'raw'

        Returns:
            bytes: Formatted certificate DER bytes

        """
        self.ensure_one()
        if not self.certificate_pem:
            raise UserError(self.env._("No certificate loaded"))

        cert = x509.load_pem_x509_certificate(
            base64.b64decode(self.with_context(bin_size=False).certificate_pem),
        )
        der_bytes = cert.public_bytes(serialization.Encoding.DER)
        return self._format_bytes(der_bytes, formatting)

    def get_credential_dict(self) -> dict[str, Any]:
        """Get credential as dictionary (for multi-value credentials).

        Rate limiting AND audit logging are both enforced upstream in
        _compute_cached_plaintext: reading self.credential_data below triggers
        the compute cascade, which (a) rate-limits the plaintext access via
        _enforce_access_rate_limit (raising ValidationError + an out-of-band
        'read_rate_limited' audit row on denial) and (b) writes exactly one
        'read' audit entry per (record, transaction). This method therefore no
        longer duplicates the rate-limit / audit logic — every plaintext path
        (direct credential_value read, JSON accessors, this method) is gated at
        the single decrypt choke point.
        """
        self.ensure_one()

        # Only 'json' storage has a meaningful dict view. For 'simple'
        # storage, callers must read credential_value directly — we do
        # NOT fall back to wrapping it as {"value": ...} because that
        # shape used to leak into storage on subsequent inverse writes
        # and silently corrupt the simple value. See the removed fallback
        # and TestSimpleToJsonStorageTransition for context.
        if self.storage_method != "json":
            return {}

        if self.credential_data and self.credential_data != "{}":
            try:
                return json.loads(self.credential_data)
            except json.JSONDecodeError, ValueError:
                _logger.warning(
                    "Failed to parse credential_data as JSON for %s %s",
                    self._name,
                    self.id,
                )

        return {}

    def get_credential_value_by_key(self, key: str, default: Any = None) -> Any:
        """Get specific value from JSON credential by key."""
        self.ensure_one()
        data = self.get_credential_dict()
        return data.get(key, default)

    def increment_usage(self, success: bool = True):
        """Increment credential usage statistics.

        Updates usage_count, success_count/error_count, and last_used_at.
        Called after each credential use to track statistics.

        Args:
            success: Whether the operation using this credential was successful

        """
        self.ensure_one()
        vals = {
            "usage_count": self.usage_count + 1,
            "last_used_at": fields.Datetime.now(),
        }
        if success:
            vals["success_count"] = self.success_count + 1
        else:
            vals["error_count"] = self.error_count + 1
        self.with_context(**{self._INTERNAL_STATS_UPDATE_KEY: True}).write(vals)

    def _log_access(self, operation: str = "read"):
        """Log credential access for audit trail."""
        self.ensure_one()

        # Get IP address from HTTP request if available
        source_ip = False
        try:
            if request and hasattr(request, "httprequest"):
                raw_ip = request.httprequest.remote_addr
                # Validate IP address format to prevent log injection
                if raw_ip:
                    try:
                        # This validates IPv4 and IPv6 addresses
                        ipaddress.ip_address(raw_ip)
                        source_ip = raw_ip
                    except ValueError:
                        # Invalid IP format - log sanitized value
                        _logger.warning(
                            "Invalid IP address format in request: %s",
                            raw_ip[:50] if raw_ip else "None",
                        )
                        source_ip = "invalid"
        except Exception:
            # No request context (e.g., cron job, shell) — source_ip stays unknown.
            _logger.debug("No HTTP request context for access log", exc_info=True)

        self.env["credential.access.log"].sudo().create(
            {
                "credential_id": self.id,
                # Denormalized so the audit row stays readable after the
                # credential / user is deleted (FKs are ondelete=set null).
                "credential_name": self.name,
                "user_id": self.env.uid,
                "user_login": self.env.user.login,
                "company_id": self.company_id.id if self.company_id else False,
                "operation": operation,
                "timestamp": fields.Datetime.now(),
                "source_ip": source_ip,
            },
        )

    def _log_access_guarded(self, operation: str = "read") -> None:
        """Audit a read without breaking Odoo 19 readonly-route RW retry.

        On a readonly cursor (readonly HTTP route), an ORM ``create`` on the
        audit-log model raises ``ReadOnlySqlTransaction``. If a compute-time
        ``try/except Exception`` swallowed that, the framework's read-write
        retry would never trigger. So when the cursor is readonly we route the
        audit write through the out-of-band fresh RW cursor instead of writing
        on the readonly cursor at all. On a normal RW cursor we log inline.
        """
        self.ensure_one()
        if self.env.cr.readonly:
            self._log_access_out_of_band(operation)
        else:
            self._log_access(operation)

    def _enforce_access_rate_limit(self) -> None:
        """Rate-limit a genuine plaintext-access read; deny if exceeded.

        Single choke point shared by every decrypt path that exposes plaintext
        to a caller: ``_compute_cached_plaintext`` (credential_value and every
        JSON accessor), private-key PEM extraction, and ``_sign``. On denial it
        writes an out-of-band ``read_rate_limited`` audit row (survives the
        ValidationError rollback) and raises.

        All access kinds (read / use / sign) deliberately share ONE per-user,
        per-credential bucket keyed on ``"read"`` — the configured cap is
        "max decryption operations per user per hour", so signing and reading
        must count against the same limit rather than getting 100 each.

        Internal re-encryption / migration paths MUST NOT call this — they read
        ciphertext to re-encrypt, they do not expose plaintext to a user.
        """
        self.ensure_one()
        if not self.id:
            return
        # Read the admin-gated control fields via sudo: the decrypt path can
        # run for a base.group_system user who is not in group_credential_admin
        # (credential payload fields are group_system, the rate-limit config is
        # group_credential_admin), and a plain attribute read would AccessError.
        config = self.sudo()
        if not (config.enable_rate_limiting and config.rate_limit_max_attempts > 0):
            return

        limiter = get_credential_rate_limiter(self.env)
        result = limiter.check_rate_limit(
            credential_id=self.id,
            user_id=self.env.uid,
            operation="read",
            limit=config.rate_limit_max_attempts,
            window_minutes=60,
        )
        if result["allowed"]:
            return

        # SECURITY: log to the Python logger BEFORE raising — this survives the
        # DB rollback that the ValidationError triggers on the caller's txn.
        _logger.warning(
            "SECURITY: Rate limit exceeded for credential '%s' (id=%s) "
            "by user %s. Attempts: %d/%d in %d minutes.",
            self.name,
            self.id,
            self.env.uid,
            result["attempts"],
            result["limit"],
            result["window_minutes"],
        )
        # Persist the audit row via a dedicated cursor so it survives the
        # ValidationError rollback on the caller's transaction.
        self._log_access_out_of_band("read_rate_limited")
        raise ValidationError(
            self.env._(
                "Rate limit exceeded for credential '%(name)s'.\n\n"
                "You have made %(attempts)s decryption attempts in the last %(window)s minutes.\n"
                "Limit: %(limit)s attempts per hour.",
            )
            % {
                "name": self.name,
                "attempts": result["attempts"],
                "window": result["window_minutes"],
                "limit": result["limit"],
            },
        )

    def _log_access_out_of_band(self, operation: str) -> None:
        """Write an audit-log row via a dedicated cursor.

        Used for audit events that must survive the caller's transaction
        rollback — specifically rate-limit-denied reads, where the caller
        raises ValidationError immediately after logging and the normal
        _log_access row would be rolled back with it.

        If the out-of-band write itself fails, we fall back to the
        rollback-coupled path and log a warning. Audit integrity is best-
        effort: never let a failed audit break credential access.
        """
        self.ensure_one()
        try:
            with self.env.registry.cursor() as cr:
                env = self.env(cr=cr)
                env["credential.access.log"].sudo().create(
                    {
                        "credential_id": self.id,
                        # Denormalized so the row outlives the credential/user.
                        "credential_name": self.name,
                        "user_id": self.env.uid,
                        "user_login": self.env.user.login,
                        "company_id": (
                            self.company_id.id if self.company_id else False
                        ),
                        "operation": operation,
                        "timestamp": fields.Datetime.now(),
                    },
                )
        except Exception as e:
            _logger.error(
                "Out-of-band audit log failed for credential %s op=%s: %s. "
                "Falling back to rollback-coupled write.",
                self.id,
                operation,
                e,
            )
            try:
                self._log_access(operation)
            except Exception as inner:
                _logger.error(
                    "Fallback audit log ALSO failed for credential %s: %s",
                    self.id,
                    inner,
                )

    def mark_as_used(self):
        """Mark credential as recently used."""
        self.ensure_one()
        self.with_context(**{self._INTERNAL_STATS_UPDATE_KEY: True}).write(
            {"last_used_at": fields.Datetime.now()}
        )
        self._log_access("use")

    def set_credential_dict(self, data_dict: dict[str, Any]):
        """Set credential from dictionary.

        Note: This method directly encrypts to credential_value_encrypted
        instead of assigning to credential_data, because when called from
        within an inverse method, Odoo does not trigger the inverse of
        computed fields.
        """
        self.ensure_one()

        if not isinstance(data_dict, dict):
            raise ValidationError(self.env._("Credential data must be a dictionary"))

        self._log_access("write")
        json_str = json.dumps(data_dict)

        # Validate size limits (same as _inverse_credential_data)
        data_size = len(json_str.encode("utf-8"))
        if data_size > MAX_CREDENTIAL_DATA_SIZE:
            raise ValidationError(
                self.env._(
                    "Credential data exceeds maximum size!\n\nSize: %(size)s bytes\nMaximum: %(max)s bytes (64KB)",
                )
                % {"size": data_size, "max": MAX_CREDENTIAL_DATA_SIZE},
            )

        # Validate JSON depth
        try:
            _check_json_depth(data_dict)
        except ValueError as e:
            raise ValidationError(
                self.env._(
                    "Invalid JSON structure!\n\nError: %(error)s\nMaximum nesting depth allowed: %(max)s levels",
                )
                % {"error": str(e), "max": MAX_JSON_NESTING_DEPTH},
            ) from e

        # Encrypt directly to avoid inverse chain issues
        # When called from _inverse_credential_json_field, assigning to
        # credential_data does not trigger _inverse_credential_data
        if json_str and json_str != "{}":
            self.credential_value_encrypted = self._encrypt_value(json_str)
        else:
            self.credential_value_encrypted = False

    def _sign(self, message, hashing_algorithm="sha256", formatting="encodebytes"):
        """Sign a message using the certificate's private key.

        Args:
            message: Message to sign (str or bytes)
            hashing_algorithm: 'sha256' or 'sha1'
            formatting: Output format

        Returns:
            bytes: Formatted signature

        """
        self.ensure_one()

        if self.category_code != "certificate":
            raise UserError(
                self.env._("Signing is only available for certificate credentials")
            )

        # Rate-limit + audit the signing operation exactly once here. Reading
        # private_key_pem below is done with _credential_internal_access=True so
        # _compute_private_key_pem does NOT re-enforce (which would double-count
        # the rate limiter and emit a second audit row for the same operation).
        self._enforce_access_rate_limit()

        if not self.certificate_is_valid:
            raise UserError(
                self.certificate_loading_error
                or self.env._("Certificate is not valid, its validity has expired."),
            )

        # Single decrypt of the private key (flagged internal so the compute
        # skips its own enforcement; bin_size=False to get the full value).
        pk_pem = self.with_context(
            _credential_internal_access=True,
            bin_size=False,
        ).private_key_pem
        if not pk_pem:
            raise UserError(
                self.env._(
                    "No private key linked to the certificate, it is required to sign documents.",
                ),
            )

        # Audit the actual signing use (rate limit already enforced above).
        self._log_access_guarded("use")

        # Import signing utilities from cryptography

        if not isinstance(message, bytes):
            message = message.encode("utf-8")

        hash_algorithms = {
            # SHA1 is kept for interop with legacy signature formats (e.g. CFDI
            # 3.3, older SAT endpoints); callers select sha256 when available.
            "sha1": hashes.SHA1(),  # noqa: S303
            "sha256": hashes.SHA256(),
        }
        if hashing_algorithm not in hash_algorithms:
            raise UserError(
                self.env._(
                    "Unsupported hashing algorithm '%s'. Use 'sha1' or 'sha256'."
                )
                % hashing_algorithm,
            )

        private_key = serialization.load_pem_private_key(
            base64.b64decode(pk_pem),
            None,
        )

        if isinstance(private_key, rsa.RSAPrivateKey):
            signature = private_key.sign(
                message,
                padding.PKCS1v15(),
                hash_algorithms[hashing_algorithm],
            )
        elif isinstance(private_key, ec.EllipticCurvePrivateKey):
            signature = private_key.sign(
                message,
                ec.ECDSA(hash_algorithms[hashing_algorithm]),
            )
        else:
            raise UserError(self.env._("Unsupported key type. Supported: RSA, EC"))

        return self._format_bytes(signature, formatting)
