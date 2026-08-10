import logging
import os

from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# (model, table, [(plain_field, is_binary)], [attachment fields to purge outright])
#
# The binary fields moved from ir.attachment rows to Fernet-encrypted columns;
# the char ones from a varchar column. ``purge_only`` names attachment-backed
# fields that stop being persisted altogether — certificate.key.pem_key is the
# normalized PEM of a private key and has no encrypted successor, it is
# recomputed on demand.
_MIGRATIONS = (
    {
        "model": "certificate.key",
        "table": "certificate_key",
        "binary": ["content"],
        "char": ["password"],
        "purge_only": ["pem_key"],
    },
    {
        "model": "certificate.certificate",
        "table": "certificate_certificate",
        "binary": ["content"],
        "char": ["pkcs12_password"],
        "purge_only": [],
    },
)


def _harvest(env, spec):
    """Read the legacy plaintext for one model, without writing anything.

    :return: ``{record_id: {field: value}}`` for rows that carry any legacy
        plaintext, plus the attachment recordset that has to be purged.
    """
    legacy = {}

    attachments = (
        env["ir.attachment"]
        .sudo()
        .with_context(bin_size=False)
        .search(
            [
                ("res_model", "=", spec["model"]),
                ("res_field", "in", spec["binary"] + spec["purge_only"]),
            ],
        )
    )
    for attachment in attachments:
        if attachment.res_field in spec["binary"] and attachment.datas:
            legacy.setdefault(attachment.res_id, {})[attachment.res_field] = (
                attachment.datas
            )

    for field in spec["char"]:
        # Read the column directly: the field is a non-stored compute by the
        # time this hook runs, so the ORM would report the (still empty)
        # decrypted value rather than the legacy plaintext. The interpolated
        # identifiers come from the module-local _MIGRATIONS literal above and
        # never from data; the value comparison stays parameterized.
        env.cr.execute(
            f'SELECT id, "{field}" FROM "{spec["table"]}" '
            f'WHERE "{field}" IS NOT NULL AND "{field}" != %s',
            ("",),
        )
        for record_id, value in env.cr.fetchall():
            legacy.setdefault(record_id, {})[field] = value

    return legacy, attachments


def post_init_hook(env):
    """Re-encrypt existing certificate/key material and purge the plaintext.

    Harvest first, then check the key, then write, then purge: an install that
    cannot encrypt must abort before it has touched a single row, and the
    plaintext must survive until its ciphertext is committed.
    """
    harvested = [(spec, *_harvest(env, spec)) for spec in _MIGRATIONS]
    total = sum(len(legacy) for _spec, legacy, _atts in harvested)

    if total and not os.environ.get("ODOO_API_ENCRYPTION_KEY"):
        raise ValidationError(
            env._(
                "certificate_encryption cannot be installed: %(count)s existing "
                "certificate/key record(s) hold plaintext secrets that must be "
                "encrypted, but ODOO_API_ENCRYPTION_KEY is not set.\n\n"
                "Generate a Fernet key and export it in the server's environment, "
                "then install this module again:\n\n"
                '  python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"',
                count=total,
            ),
        )

    # Stamp what the rotation migration would otherwise treat as untracked, so
    # a later ODOO_API_ENCRYPTION_KEY rotation skips rows already on the
    # current key instead of re-encrypting every certificate in the database.
    current_version = env["credential.credential"]._get_current_encryption_key_version()

    migrated = 0
    for spec, legacy, attachments in harvested:
        model = env[spec["model"]].sudo().with_context(active_test=False)
        done = model.browse()
        for record_id, values in legacy.items():
            record = model.browse(record_id).exists()
            if not record:
                continue
            # Writing the plaintext names goes through the inverse methods,
            # i.e. the same encryption path a normal upload takes.
            record.write(values)
            done |= record
            migrated += 1

        # Flush before dropping the source: the ciphertext has to be in the
        # database before the plaintext leaves it.
        env.cr.flush()
        if current_version:
            done._stamp_encryption_key_version(current_version)
        attachments.unlink()
        for field in spec["char"]:
            # Identifiers from _MIGRATIONS, as in _harvest.
            env.cr.execute(f'UPDATE "{spec["table"]}" SET "{field}" = NULL')

        if spec["binary"] or spec["char"]:
            _logger.info(
                "certificate_encryption: encrypted %d %s record(s), purged %d "
                "plaintext attachment(s) and cleared %s",
                len(legacy),
                spec["model"],
                len(attachments),
                ", ".join(f"{spec['table']}.{f}" for f in spec["char"]),
            )

    _logger.info(
        "certificate_encryption: migration complete, %d record(s) re-encrypted",
        migrated,
    )
