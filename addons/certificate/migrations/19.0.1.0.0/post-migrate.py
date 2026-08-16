import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

_MIGRATIONS = (
    {
        "model": "certificate.key",
        "fields": (("content", "content_plain"), ("password", "password_plain")),
    },
    {
        "model": "certificate.certificate",
        "fields": (
            ("content", "content_plain"),
            ("pkcs12_password", "pkcs12_password_plain"),
        ),
    },
)


def _remove_persisted_pem_keys(env):
    """Drop the normalized private-key PEM, which is no longer stored.

    Through the ORM rather than SQL: the field was attachment-backed, so a
    plain DELETE would leave the PEM files sitting in the filestore.
    """
    attachments = env["ir.attachment"].search(
        [("res_model", "=", "certificate.key"), ("res_field", "=", "pem_key")],
    )
    count = len(attachments)
    attachments.unlink()
    return count


def _encrypt_cleartext(env, spec):
    model = env[spec["model"]].with_context(active_test=False, bin_size=False)
    cleartext_fields = [cleartext for _exposed, cleartext in spec["fields"]]
    domain = ["|"] * (len(cleartext_fields) - 1)
    domain += [(field, "!=", False) for field in cleartext_fields]

    records = model.search(domain)
    for record in records:
        values = {}
        for exposed, cleartext in spec["fields"]:
            value = record[cleartext]
            if value:
                values[exposed] = value
        if values:
            record.write(values)

    return records


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    removed = _remove_persisted_pem_keys(env)

    if not env["encryption.mixin"]._is_encryption_available():
        _logger.info(
            "certificate: removed %d persisted private-key PEM(s); certificate "
            "and key material stays unencrypted because "
            "ODOO_API_ENCRYPTION_KEY is not set. Set it and run the encryption "
            "key rotation to encrypt the existing rows.",
            removed,
        )
        return

    key_version = env["encryption.mixin"]._get_current_encryption_key_version()
    migrated = 0
    for spec in _MIGRATIONS:
        records = _encrypt_cleartext(env, spec)
        env.cr.flush()
        if key_version:
            records._stamp_encryption_key_version(key_version)
        migrated += len(records)
        _logger.info(
            "certificate: encrypted %d %s record(s) at rest",
            len(records),
            spec["model"],
        )

    _logger.info(
        "certificate: removed %d persisted private-key PEM(s), %d record(s) "
        "moved to encrypted storage",
        removed,
        migrated,
    )
