import base64
import logging
import os
import threading
import time
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# Cooldown between "encryption key not configured" warnings, process-wide.
# The previous implementation used a one-shot latch that never reset, so a
# worker that logged the warning once would stay silent for the rest of its
# life — even if the operator fixed and re-broke the key configuration.
# 5 minutes is short enough that recovery events are visible and long enough
# that a crashing cron job won't spam the log on every iteration.
_ENCRYPTION_KEY_WARNING_COOLDOWN_SECONDS = 300

# Process-wide state for the encryption key machinery. Previously these lived
# as class attributes mutated through ``type(self)``, which meant every model
# that inherited the mixin got its OWN cache and its OWN warning latch.
# Rotating the key at runtime and only invalidating one model's cache left
# sibling models returning stale versions. Module-level state + a lock gives
# every consumer one authoritative view, and ``_invalidate_key_version_cache``
# now clears the real storage rather than one dynamic class' shadow copy.
_KEY_STATE_LOCK = threading.Lock()

# Module-level mutable state held in a single dict so helpers can update
# fields via item-assignment rather than ``global`` rebinds. This keeps
# pylint happy (no ``global-statement`` on every mutation) and makes the
# shared state easy to see in one place.
_KEY_STATE: dict[str, Any] = {
    "version_cache": None,
    "version_cache_checked": False,
    "missing_warning_last_at": 0.0,
}


class CredentialEncryptionMixin(models.AbstractModel):
    """Abstract mixin providing encryption/decryption for credentials.

    This mixin provides:
    - _get_encryption_key(): Retrieve encryption key from environment
    - _encrypt_value(value): Encrypt a string value
    - _decrypt_value(encrypted_value): Decrypt an encrypted value

    Security:
    - Encryption key is NEVER stored in database
    - Uses environment variable: ODOO_API_ENCRYPTION_KEY
    - Fernet symmetric encryption (AES-128 in CBC mode with HMAC)
    """

    _name = "credential.encryption.mixin"
    _description = "Credential Encryption Mixin"

    # Registry of Fernet-encrypted columns on the inheriting model, as
    # (plain_field, encrypted_field, is_binary) tuples. Every consumer that
    # stores ciphertext MUST declare its columns here — this is what the
    # suite-wide key-rotation migration (credential.credential.
    # action_migrate_encryption_keys) walks to re-encrypt data after
    # ODOO_API_ENCRYPTION_KEY changes. An encrypted column that is not
    # registered becomes permanently undecryptable once the old key env
    # vars are retired.
    _ENCRYPTED_FIELD_PAIRS: tuple = ()

    encryption_key_version = fields.Integer(
        readonly=True,
        help="Version of the encryption key used for this record's encrypted "
        "columns (for key-rotation tracking). 0/unset means untracked — the "
        "rotation migration treats such rows as eligible.",
    )

    # ==================== Generic Encrypted Field Helpers ====================
    #
    # Usage example (shown as prose to keep linters from parsing it as code)::
    #
    #   Inherit 'credential.encryption.mixin', declare a Binary field
    #   '<name>_encrypted', a Char '<name>' with compute='_compute_<name>' and
    #   inverse='_inverse_<name>', then delegate both to
    #   _compute_encrypted_char_field / _inverse_encrypted_char_field.

    # ------------------------------------------------------------
    # COMPUTE METHODS
    # ------------------------------------------------------------

    def _compute_encrypted_char_field(
        self,
        encrypted_field: str,
        target_field: str,
        safe: bool = True,
    ) -> None:
        """Generic compute method for decrypting a binary field to a char field.

        Decrypts the value from encrypted_field and assigns it to target_field.

        Args:
            encrypted_field: Name of the Binary field containing encrypted data
            target_field: Name of the Char field to store decrypted value
            safe: If True (default), use safe decryption (no exceptions).
                  If False, exceptions propagate to caller.

        Example:
            @api.depends('oauth_secret_encrypted')
            def _compute_oauth_secret(self):
                self._compute_encrypted_char_field('oauth_secret_encrypted', 'oauth_secret')

        """
        for record in self:
            encrypted_value = getattr(record, encrypted_field)
            if safe:
                decrypted = record._decrypt_value_safe(encrypted_value, default=False)
            else:
                decrypted = (
                    record._decrypt_value(encrypted_value) if encrypted_value else False
                )
            setattr(record, target_field, decrypted)

    def _compute_encrypted_binary_field(
        self,
        encrypted_field: str,
        target_field: str,
        safe: bool = True,
    ) -> None:
        """Generic compute method for decrypting a binary field to another binary field.

        Decrypts the Fernet-encrypted value from encrypted_field and assigns
        the original binary data to target_field.

        Args:
            encrypted_field: Name of the Binary field containing encrypted data
            target_field: Name of the Binary field to store decrypted value
            safe: If True (default), use safe decryption (no exceptions).
                  If False, exceptions propagate to caller.

        Example:
            @api.depends('private_key_encrypted')
            def _compute_private_key(self):
                self._compute_encrypted_binary_field('private_key_encrypted', 'private_key')

        """
        for record in self:
            encrypted_value = getattr(record, encrypted_field)
            if not encrypted_value:
                setattr(record, target_field, False)
                continue

            try:
                # Fernet decrypt returns bytes, which we return directly
                # The encrypted_value is already bytes from the Binary field
                decrypted_bytes = record._decrypt_binary_value(encrypted_value)
                setattr(record, target_field, decrypted_bytes)
            except Exception as e:
                if safe:
                    _logger.warning(
                        "Safe binary decrypt failed for %s record %s: %s",
                        record._name,
                        getattr(record, "id", "new"),
                        e,
                    )
                    setattr(record, target_field, False)
                else:
                    raise

    # ------------------------------------------------------------
    # INVERSE METHODS
    # ------------------------------------------------------------

    def _inverse_encrypted_char_field(
        self,
        source_field: str,
        encrypted_field: str,
    ) -> None:
        """Generic inverse method for encrypting a char field to a binary field.

        Encrypts the value from source_field and stores it in encrypted_field.

        Args:
            source_field: Name of the Char field containing plain text value
            encrypted_field: Name of the Binary field to store encrypted data

        Example:
            def _inverse_oauth_secret(self):
                self._inverse_encrypted_char_field('oauth_secret', 'oauth_secret_encrypted')

        """
        for record in self:
            value = getattr(record, source_field)
            if value:
                setattr(record, encrypted_field, record._encrypt_value(value))
            else:
                setattr(record, encrypted_field, False)

    def _inverse_encrypted_binary_field(
        self,
        source_field: str,
        encrypted_field: str,
    ) -> None:
        """Generic inverse method for encrypting a binary field to another binary field.

        Encrypts the binary value from source_field and stores it in encrypted_field.

        Args:
            source_field: Name of the Binary field containing plain binary value
            encrypted_field: Name of the Binary field to store encrypted data

        Example:
            def _inverse_private_key(self):
                self._inverse_encrypted_binary_field('private_key', 'private_key_encrypted')

        """
        for record in self:
            value = getattr(record, source_field)
            if value:
                setattr(record, encrypted_field, record._encrypt_binary_value(value))
            else:
                setattr(record, encrypted_field, False)

    # ------------------------------------------------------------
    # HELPER METHODS
    # ------------------------------------------------------------

    @staticmethod
    def _coerce_fernet_token(encrypted_value: bytes) -> bytes:
        """Return a Fernet token regardless of on-disk wire format.

        Two legal shapes can sit in an encrypted Binary column on this
        model:

        * **Canonical**: the raw Fernet token (ASCII bytes starting with
          ``b"gAAAAA"``). This is what ``_encrypt_value`` has always
          produced for char fields, and what ``_encrypt_binary_value``
          produces after the 19.0.1.0.2 cleanup.
        * **Legacy double-base64**: ``base64.b64encode(fernet_token)``.
          This is what ``_encrypt_binary_value`` produced before the
          cleanup — the outer b64 is redundant since the token is
          already base64url internally, but existing certificate /
          PKCS12 / private-key rows on customer databases carry it and
          a migration would force an all-or-nothing re-encrypt under
          the current key, which is exactly the cross-key hazard we're
          trying to avoid.

        Both shapes pass through here. The check is literally "does
        this start with the Fernet header byte" — anything else is
        assumed to be the legacy wrap and gets one ``b64decode`` applied.
        This is the same sniff already used by ``_decrypt_value`` for
        char fields, hoisted out so the char and binary paths finally
        agree.
        """
        if isinstance(encrypted_value, str):
            encrypted_value = encrypted_value.encode("utf-8")
        else:
            encrypted_value = bytes(encrypted_value)
        if encrypted_value.startswith(b"gAAAAA"):
            return encrypted_value
        try:
            return base64.b64decode(encrypted_value)
        except Exception as e:
            # Static method: no `self.env._()` available; message is an
            # internal error surfaced via the caller's translated context.
            raise ValidationError("Invalid encrypted binary data") from e

    def _decrypt_binary_value(self, encrypted_value: bytes) -> bytes | bool:
        """Decrypt binary data using Fernet symmetric encryption.

        Mirrors _decrypt_value: supports key rotation AND degrades to False
        when the encryption key env var is missing, so certificate-type and
        value-type credentials behave identically under a misconfigured server.

        Accepts both the canonical raw-Fernet-token on-disk shape and the
        legacy double-base64 shape via ``_coerce_fernet_token``; this makes
        the module robust to existing databases that were written by the
        pre-cleanup ``_encrypt_binary_value``.
        """
        if not encrypted_value:
            return False

        allow_fallback = getattr(self, "allow_key_fallback", True)
        encrypted_bytes = self._coerce_fernet_token(encrypted_value)

        try:
            cipher = Fernet(self._get_encryption_key())
            return base64.b64encode(cipher.decrypt(encrypted_bytes))
        except ValidationError:
            self._warn_encryption_key_missing(binary=True)
            return False
        except InvalidToken:
            if not allow_fallback:
                raise ValidationError(
                    self.env._(
                        "Failed to decrypt binary with current key. Fallback disabled."
                    ),
                ) from None
            _logger.debug(
                "Current key failed for %s binary decryption, trying old keys",
                self._name,
            )
        except Exception as e:
            _logger.error("Binary decryption failed: %s", e)
            raise ValidationError(
                self.env._("Failed to decrypt binary value: %s") % str(e)
            ) from e

        current_version = self._get_current_encryption_key_version()
        if current_version and current_version > 1:
            for version in range(current_version - 1, 0, -1):
                try:
                    old_key = self._get_encryption_key(version=version)
                    if old_key:
                        cipher = Fernet(old_key)
                        _logger.info(
                            "Binary decrypted with old key v%s. Consider running key migration.",
                            version,
                        )
                        return base64.b64encode(cipher.decrypt(encrypted_bytes))
                except Exception:
                    _logger.debug(
                        "Binary decryption with key v%s failed",
                        version,
                        exc_info=True,
                    )
                    continue

        raise ValidationError(
            self.env._("Failed to decrypt binary value with any available key."),
        )

    def _decrypt_value(self, encrypted_value: bytes) -> str | bool:
        """Decrypt an encrypted value using Fernet symmetric encryption.

        Supports KEY ROTATION: Tries current key first, then falls back to old key versions.
        This allows seamless decryption during key rotation transitions.

        Per-Credential Preference: If the model has an 'allow_key_fallback' field,
        it will be respected. Set to False to fail fast if current key doesn't work.

        Fallback order:
        1. Try current key (ODOO_API_ENCRYPTION_KEY)
        2. Try versioned keys in reverse order (newest to oldest) - if fallback allowed

        Args:
            encrypted_value (bytes): Encrypted value

        Returns:
            str: Decrypted plain text value, or False if encrypted_value is empty

        Raises:
            ValidationError: If decryption fails with all available keys

        """
        if not encrypted_value:
            return False

        # Normalize to a raw Fernet token regardless of on-disk shape.
        # _coerce_fernet_token handles both the canonical raw-token shape
        # AND the legacy double-base64 shape that earlier versions wrote
        # through _encrypt_binary_value. Sharing this helper between the
        # char and binary paths means neither path can diverge again.
        encrypted_bytes = self._coerce_fernet_token(encrypted_value)

        # Check if this model has allow_key_fallback field (per-credential preference)
        allow_fallback = getattr(self, "allow_key_fallback", True)

        # Try current key first (most common case)
        try:
            cipher = Fernet(self._get_encryption_key())
            decrypted = cipher.decrypt(encrypted_bytes)
            return decrypted.decode("utf-8")
        except ValidationError:
            # Encryption key not configured — return False so callers degrade
            # gracefully (e.g. computed fields return empty, cron jobs use
            # fallback defaults) instead of crashing the entire compute chain.
            self._warn_encryption_key_missing(binary=False)
            return False
        except InvalidToken:
            # Current key failed
            if not allow_fallback:
                # Fail fast - don't try old keys
                _logger.error(
                    "Current key failed for %s record %s. Fallback disabled (allow_key_fallback=False).",
                    self._name,
                    self.id,
                )
                raise ValidationError(
                    self.env._(
                        "Failed to decrypt credential with current key.\n\n"
                        "This credential has fallback disabled (allow_key_fallback=False). "
                        "Either:\n"
                        "1. Enable fallback temporarily to decrypt with old key\n"
                        "2. Fix the encryption key configuration\n"
                        "3. Re-create this credential with the current key",
                    ),
                ) from None
            # Fallback enabled - try old versions
            _logger.debug(
                "Current key failed for %s record %s, trying old key versions",
                self._name,
                self.id,
            )
        except Exception as e:
            _logger.error(
                "Decryption failed for %s record %s: %s", self._name, self.id, e
            )
            raise ValidationError(
                self.env._("Failed to decrypt value: %s") % str(e)
            ) from e

        # Try old key versions (for data encrypted with previous keys)
        current_version = self._get_current_encryption_key_version()
        if current_version and current_version > 1:
            # Try versions in reverse order (newest old key first)
            for version in range(current_version - 1, 0, -1):
                try:
                    old_key = self._get_encryption_key(version=version)
                    if old_key:
                        cipher = Fernet(old_key)
                        decrypted = cipher.decrypt(encrypted_bytes)
                        _logger.info(
                            "Successfully decrypted %s record %s using old key "
                            "version %s. Consider running key migration.",
                            self._name,
                            self.id,
                            version,
                        )
                        return decrypted.decode("utf-8")
                except InvalidToken:
                    # This version didn't work either, try next
                    continue
                except Exception:
                    _logger.debug(
                        "Decryption with old key v%s for %s record %s failed",
                        version,
                        self._name,
                        self.id,
                        exc_info=True,
                    )
                    continue

        # All keys failed
        _logger.error(
            "Failed to decrypt value for %s record %s: Invalid encryption key "
            "(tried current + %d old versions)",
            self._name,
            self.id,
            current_version - 1 if current_version else 0,
        )
        raise ValidationError(
            self.env._(
                "Failed to decrypt value. Encryption key may have changed.\n\n"
                "If you recently rotated encryption keys, ensure old keys are still "
                "available as ODOO_API_ENCRYPTION_KEY_V1, V2, etc.\n\n"
                "Run the key migration tool to re-encrypt all credentials with the new key.",
            ),
        )

    def _decrypt_value_safe(
        self,
        encrypted_value: bytes,
        default: Any = False,
    ) -> str | Any:
        """Safely decrypt an encrypted value, returning default on any error.

        Unlike _decrypt_value(), this method never raises exceptions.
        Useful for computed fields where decryption failure should not
        break the entire record display.

        Args:
            encrypted_value (bytes): Encrypted value to decrypt
            default: Value to return on decryption failure (default: False)

        Returns:
            str: Decrypted value, or default if decryption fails

        """
        if not encrypted_value:
            return default

        try:
            return self._decrypt_value(encrypted_value)
        except Exception as e:
            _logger.warning(
                "Safe decrypt failed for %s record %s: %s",
                self._name,
                getattr(self, "id", "new"),
                e,
            )
            return default

    def _warn_encryption_key_missing(self, binary: bool) -> None:
        """Rate-limited warning when ODOO_API_ENCRYPTION_KEY is absent.

        Single entry point shared by every decrypt path. Uses a monotonic
        time-based cooldown (not a one-shot latch) so recovery / re-break
        cycles stay visible to operators — the regression the file header
        comment warns against. Cooldown state is module-level so every
        mixin consumer shares one clock.
        """
        now = time.monotonic()
        with _KEY_STATE_LOCK:
            if (
                now - _KEY_STATE["missing_warning_last_at"]
                < _ENCRYPTION_KEY_WARNING_COOLDOWN_SECONDS
            ):
                return
            _KEY_STATE["missing_warning_last_at"] = now
        if binary:
            _logger.warning(
                "Cannot decrypt binary credentials: encryption key not "
                "configured. Set ODOO_API_ENCRYPTION_KEY environment variable.",
            )
        else:
            _logger.warning(
                "Cannot decrypt credentials: encryption key not configured. "
                "Set ODOO_API_ENCRYPTION_KEY environment variable.",
            )

    def _encrypt_binary_value(self, value: bytes) -> bytes | bool:
        """Encrypt binary data using Fernet symmetric encryption.

        Args:
            value: Binary data to encrypt (base64-encoded from Odoo Binary field
                uploads; ``_inverse_encrypted_binary_field`` passes through
                whatever Odoo gave it).

        Returns:
            bytes: Raw Fernet token (ASCII, starts with ``b"gAAAAA"``), stored
            verbatim in the Binary column. The char and binary paths now agree
            on wire format; the legacy double-base64 shape produced by earlier
            versions of this module is still readable via
            ``_coerce_fernet_token`` on the decrypt side.

        """
        if not value:
            return False

        try:
            # Uploads arrive base64-encoded (form POST → Odoo Binary field).
            # Strip that outer wrap to get the actual file bytes before
            # handing them to Fernet; the Fernet token itself is already
            # base64url internally, so wrapping it again in base64 (the
            # pre-19.0.1.0.2 behaviour) just bloats storage by ~33% and
            # diverged us from the char-path wire format.
            raw_bytes = base64.b64decode(value)
            key = self._get_encryption_key()
            cipher = Fernet(key)
            return cipher.encrypt(raw_bytes)
        except Exception as e:
            _logger.error("Binary encryption failed: %s", e)
            raise ValidationError(
                self.env._("Failed to encrypt binary value: %s") % str(e)
            ) from e

    def _encrypt_value(
        self,
        value: str,
        key_version: int | None = None,
    ) -> bytes | bool:
        """Encrypt a string value using Fernet symmetric encryption.

        Always uses the CURRENT (latest) encryption key for new encryptions.
        This ensures that newly encrypted data uses the most recent key.

        Args:
            value (str): Plain text value to encrypt
            key_version (int, optional): Specific key version to use (for migration).
                                         If None, uses current key.

        Returns:
            bytes: Encrypted value as bytes, or False if value is empty

        Raises:
            ValidationError: If encryption fails

        """
        if not value:
            return False

        try:
            key = self._get_encryption_key(version=key_version)
            cipher = Fernet(key)
            return cipher.encrypt(value.encode("utf-8"))
        except Exception as e:
            _logger.error("Encryption failed: %s", e)
            raise ValidationError(
                self.env._("Failed to encrypt value: %s") % str(e)
            ) from e

    def _get_current_encryption_key_version(self) -> int | None:
        """Get the current encryption key version number.

        The current key (ODOO_API_ENCRYPTION_KEY) is always one version higher
        than the highest numbered old key.

        Version numbering:
        - No Vx keys exist: current version = 1
        - V1 exists: current version = 2
        - V1, V2 exist: current version = 3
        - etc.

        Performance: Result is cached in module-level state (not per concrete
        class) so every credential-bearing model shares one answer. The
        previous per-class cache left sibling models with divergent views
        after a key rotation when only one class' cache was invalidated.

        Returns:
            int: Current key version (highest_old_version + 1), or None if no key set

        """
        with _KEY_STATE_LOCK:
            if _KEY_STATE["version_cache_checked"]:
                return _KEY_STATE["version_cache"]

            if not os.environ.get("ODOO_API_ENCRYPTION_KEY"):
                _KEY_STATE["version_cache"] = None
                _KEY_STATE["version_cache_checked"] = True
                return None

            # Find highest versioned old key. Stop at 2 consecutive misses
            # so a gap at V_n + V_n+1 terminates the scan but an isolated
            # missing Vk does not (defensive against operator typos).
            highest_old_version = 0
            consecutive_misses = 0
            max_consecutive_misses = 2
            for i in range(1, 20):
                if os.environ.get(f"ODOO_API_ENCRYPTION_KEY_V{i}"):
                    highest_old_version = i
                    consecutive_misses = 0
                else:
                    consecutive_misses += 1
                    if consecutive_misses >= max_consecutive_misses:
                        break

            _KEY_STATE["version_cache"] = highest_old_version + 1
            _KEY_STATE["version_cache_checked"] = True
            return _KEY_STATE["version_cache"]

    def _get_encryption_key(self, version: int | None = None) -> bytes | None:
        """Get encryption key from environment variable.

        SECURITY: Key is NEVER stored in the database.

        Supports key rotation via versioned environment variables:
        - ODOO_API_ENCRYPTION_KEY: Current/latest key (used for new encryptions)
        - ODOO_API_ENCRYPTION_KEY_V1, V2, etc.: Old keys (for decrypting legacy data)

        Args:
            version (int, optional): Specific key version to retrieve.
                                     If None, returns current (latest) key.

        Returns:
            bytes: Fernet encryption key

        Raises:
            ValidationError: If environment variable not set or invalid

        """
        if version is None:
            # Get current/latest key
            env_var = "ODOO_API_ENCRYPTION_KEY"
        else:
            # Get specific version
            env_var = f"ODOO_API_ENCRYPTION_KEY_V{version}"

        key = os.environ.get(env_var)

        if not key:
            if version is None:
                # Current key missing - critical error
                raise ValidationError(
                    self.env._(
                        "Encryption key not configured!\n\n"
                        "The credential manager requires an encryption key to secure credentials.\n"
                        "This key MUST be set as an environment variable (NOT stored in the database).\n\n"
                        "═══════════════════════════════════════════════════════════════\n"
                        "SETUP INSTRUCTIONS:\n"
                        "═══════════════════════════════════════════════════════════════\n\n"
                        "Step 1: Generate encryption key (do this ONCE):\n"
                        "────────────────────────────────────────────────────────────────\n"
                        '  python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"\n\n'
                        "Step 2: Set environment variable:\n"
                        "────────────────────────────────────────────────────────────────\n"
                        "  export %s='<your-generated-key>'\n\n"
                        "See module documentation for detailed setup instructions.\n",
                    )
                    % env_var,
                )
            # Old key version missing - return None (will try other versions)
            return None

        try:
            # Validate key format
            Fernet(key.encode())
            return key.encode()
        except Exception as e:
            raise ValidationError(
                self.env._(
                    "Invalid encryption key format in environment variable '%(env_var)s'!\n\n"
                    "The key must be a valid Fernet key (44 characters, base64-encoded).\n\n"
                    "Generate a new key with:\n"
                    '  python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"\n\n'
                    "Error details: %(error)s",
                    env_var=env_var,
                    error=str(e),
                ),
            ) from e

    # ------------------------------------------------------------
    # KEY-ROTATION SUPPORT (suite-wide re-encryption)
    # ------------------------------------------------------------

    @api.model
    def _get_encryption_migration_models(self) -> list[str]:
        """List every concrete model with registered encrypted columns.

        Walks the registry for models that inherit this mixin AND declare a
        non-empty ``_ENCRYPTED_FIELD_PAIRS``. This is the discovery step of
        the key-rotation migration: previously the migration re-encrypted
        credential.credential only, silently stranding every other mixin
        consumer (e.g. api.endpoint.outbound's OAuth client secret) on the
        old key.
        """
        names = []
        for name in self.env.registry:
            model = self.env[name]
            # _abstract excludes the mixin itself (and any other abstract
            # carrier); transient rows are vacuumed and not worth migrating.
            if model._abstract or model._transient:
                continue
            if not isinstance(model, CredentialEncryptionMixin):
                continue
            if not model._ENCRYPTED_FIELD_PAIRS:
                continue
            names.append(name)
        return sorted(names)

    def _reencrypt_with_current_key(self) -> bool:
        """Re-encrypt this record's registered ciphertext with the current key.

        Decrypts each ``_ENCRYPTED_FIELD_PAIRS`` column (old-key fallback
        applies) and writes it back encrypted with the current key. Reads
        ciphertext directly — never the user-facing plaintext computes — so
        it does not trip the access rate limiter or the audit log.

        Returns:
            bool: True if at least one column was rewritten.

        """
        self.ensure_one()
        touched = False
        for _plain_field, enc_field, is_binary in self._ENCRYPTED_FIELD_PAIRS:
            encrypted = self.with_context(bin_size=False)[enc_field]
            if not encrypted:
                continue
            if is_binary:
                plaintext_b64 = self._decrypt_binary_value(encrypted)
                if not plaintext_b64:
                    continue
                # _decrypt_binary_value returns base64-encoded bytes, and
                # _encrypt_binary_value expects the same shape.
                self[enc_field] = self._encrypt_binary_value(plaintext_b64)
            else:
                plaintext = self._decrypt_value(encrypted)
                if not plaintext:
                    continue
                self[enc_field] = self._encrypt_value(plaintext)
            touched = True
        return touched

    def _stamp_encryption_key_version(self, version: int) -> None:
        """Record the key version on these rows without going through write().

        Raw SQL so consumers' write() overrides (mail.thread tracking,
        protected-field guards, recursion into key stamping) are not
        triggered by what is pure bookkeeping; the ORM cache is invalidated
        so same-transaction readers see the new value.
        """
        if not self.ids:
            return
        # self._table is model metadata, not user input.
        self.env.cr.execute(
            f'UPDATE "{self._table}" SET encryption_key_version = %s '
            f"WHERE id = ANY(%s)",
            [version, self.ids],
        )
        self.invalidate_recordset(["encryption_key_version"])

    @classmethod
    def _invalidate_key_version_cache(cls):
        """Invalidate the cached encryption key version.

        Call this after rotating keys or in tests. Clears the module-level
        cache shared by every mixin consumer, so rotating a key once
        propagates to every credential-bearing model.
        """
        with _KEY_STATE_LOCK:
            _KEY_STATE["version_cache"] = None
            _KEY_STATE["version_cache_checked"] = False
