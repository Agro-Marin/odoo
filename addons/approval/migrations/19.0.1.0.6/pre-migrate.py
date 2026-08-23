import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute(
        """
        SELECT id, name->>'en_US'
        FROM approval_category
        WHERE sequence_code IS NULL OR sequence_code = ''
        ORDER BY id
        """,
    )
    missing = cr.fetchall()

    cr.execute(
        """
        SELECT sequence_code, company_id, array_agg(id ORDER BY id)
        FROM approval_category
        GROUP BY sequence_code, company_id
        HAVING count(*) > 1
        ORDER BY sequence_code
        """,
    )
    duplicates = cr.fetchall()

    if not missing and not duplicates:
        _logger.info("t22196 guard: 0 offenders, sequence_code is clean.")
        return

    lines = []
    if missing:
        lines.append("Categories with a missing/empty sequence_code:")
        lines += [f"  - id={cid} name={name!r}" for cid, name in missing]
    if duplicates:
        lines.append("Duplicate sequence_code per company (NULLS NOT DISTINCT):")
        lines += [
            f"  - code={code!r} company_id={company} ids={ids}"
            for code, company, ids in duplicates
        ]
    raise ValueError(
        "t22196: cannot enforce required+unique sequence_code. Assign a real, "
        "unique code to each category below and re-run the upgrade.\n"
        + "\n".join(lines),
    )
