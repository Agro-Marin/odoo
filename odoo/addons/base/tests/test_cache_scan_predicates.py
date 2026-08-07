import logging

from odoo.orm.models.mixins._cache_scan import (
    can_scan_identity,
    can_scan_read,
    can_scan_sorted,
    can_scan_truthy,
)
from odoo.tests.common import TransactionCase

_logger = logging.getLogger(__name__)

SAMPLE_LIMIT = 20
SCALAR_TYPES = (str, int, float, bool, type(None))


class TestCacheScanPredicates(TransactionCase):
    def test_scan_predicates_agree_with_field_get(self):
        env = self.env
        violations = []
        checked = 0

        for model_name in sorted(env.registry):
            model = env[model_name]
            if model._abstract or model._transient:
                continue
            try:
                records = model.with_context(active_test=False).search(
                    [], limit=SAMPLE_LIMIT
                )
            except Exception:
                _logger.debug("skipping %s: not searchable", model_name, exc_info=True)
                continue
            if not records:
                continue

            for fname, field in model._fields.items():
                modes = {
                    "identity": can_scan_identity(field),
                    "truthy": can_scan_truthy(field),
                    "sorted": can_scan_sorted(field),
                    "read": can_scan_read(field),
                }
                if not any(modes.values()):
                    continue
                try:
                    records.fetch([fname])
                except Exception:
                    _logger.debug(
                        "skipping %s.%s: not fetchable",
                        model_name,
                        fname,
                        exc_info=True,
                    )
                    continue

                cache = field._get_cache(env)
                none_value = field.convert_to_record(None, records[:1])
                for record in records:
                    record_id = record._ids[0]
                    if record_id not in cache:
                        continue
                    raw = cache[record_id]
                    try:
                        value = record[fname]
                    except Exception:
                        _logger.debug(
                            "skipping %s.%s: __get__ raised",
                            model_name,
                            fname,
                            exc_info=True,
                        )
                        continue
                    checked += 1
                    label = f"{model_name}.{fname} ({field.type}) id={record_id}"

                    if modes["identity"]:
                        scanned = none_value if raw is None else raw
                        if scanned != value:
                            violations.append(
                                f"identity {label}: scan={scanned!r} get={value!r}"
                            )
                    if modes["truthy"] and bool(raw) != bool(value):
                        violations.append(
                            f"truthy {label}: bool(scan)={bool(raw)} "
                            f"bool(get)={bool(value)}"
                        )
                    if (
                        modes["sorted"]
                        and not isinstance(raw, SCALAR_TYPES)
                        and not hasattr(raw, "isoformat")
                    ):
                        violations.append(
                            f"sorted {label}: raw cache value is "
                            f"{type(raw).__name__}, not an orderable scalar"
                        )

        self.assertGreater(checked, 0, "swept no (field, record) pairs")
        self.assertEqual(violations[:20], [], f"{len(violations)} scan violation(s)")
