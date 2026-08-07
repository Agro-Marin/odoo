from odoo.tests.common import TransactionCase
from odoo.tools.depends_audit import audit_registry

EXEMPT: dict[str, str] = {
    "ir.model.count": (
        "not expressible: counts rows of the model it describes; no static path "
        "from ir.model to an arbitrary table's row count"
    ),
    "ir.model.inherited_model_ids": (
        "not expressible: derived from other ir.model rows' _inherit chains"
    ),
    "ir.model.view_ids": (
        "not expressible: searches ir.ui.view by model name; a new view does not "
        "invalidate this"
    ),
}


class TestDependsAudit(TransactionCase):
    def test_no_undeclared_dependency_reads(self):
        findings = list(audit_registry(self.env.registry))
        unexpected = [f for f in findings if f.label not in EXEMPT]
        self.assertFalse(
            unexpected,
            "computed field(s) read a sibling field they do not depend on, so "
            "they are computed once and never invalidated:\n"
            + "\n".join(
                f"  {f.label}: reads {', '.join(f.reads)}"
                f" (declares {', '.join(f.declared) or 'nothing'})"
                for f in unexpected
            )
            + "\n\nDeclare the dependency with @api.depends, or -- if the real "
            "input is not a static field path -- add the field to EXEMPT in "
            f"{__file__} with the reason.",
        )

    def test_exemptions_are_all_still_needed(self):
        flagged = {f.label for f in audit_registry(self.env.registry)}
        stale = sorted(set(EXEMPT) - flagged)
        stale = [
            label
            for label in stale
            if label.rsplit(".", 1)[0] in self.env
            and label.rsplit(".", 1)[1] in self.env[label.rsplit(".", 1)[0]]._fields
        ]
        self.assertFalse(
            stale,
            f"these EXEMPT entries no longer flag; delete them from {__file__}: "
            f"{stale}",
        )

    def test_audit_detects_a_deliberately_broken_field(self):
        from odoo.tools.depends_audit import audit_field

        registry = self.env.registry
        model_class = registry["res.partner"]
        field = model_class._fields["display_name"]

        def _compute_reads_a_sibling(self):
            for record in self:
                record.display_name = record.ref

        original_compute = field.compute
        original_depends = registry.field_depends.get(field, ())
        try:
            field.compute = _compute_reads_a_sibling
            registry.field_depends[field] = ()
            finding = audit_field(registry, model_class, field)
            self.assertIsNotNone(finding, "the audit failed to flag a known offender")
            self.assertIn("ref", finding.reads)
            self.assertEqual(finding.label, "res.partner.display_name")
        finally:
            field.compute = original_compute
            registry.field_depends[field] = original_depends
