"""Gate: no computed field may read a sibling field it does not depend on.

A non-stored computed field with an empty dependency set is computed once per
transaction cache and then never invalidated -- it serves a stale value with no
error, no warning and no failing query. Four instances were live in ``base``
when this gate was written:

===================================================  ==================================
field                                                stale after
===================================================  ==================================
``report.paperformat.print_page_width`` / ``_height``  flipping ``orientation``
``ir.sequence.number_next_actual``                     writing ``number_next``
``ir.sequence.date_range.number_next_actual``          writing ``number_next``
``ir.attachment.res_name``                             re-pointing ``res_id``
===================================================  ==================================

``odoo.tools.depends_audit`` finds them statically (see that module for the
method and its limits). This test pins the result to an explicit exemption list,
so a *new* offender fails here while the known-and-reviewed ones stay
documented. It is deliberately an allowlist of ``model.field`` keys rather than a
count: a bare count says nothing about which field regressed, and bumping it is
indistinguishable from fixing one.

Exempt entries fall in two kinds, and the reason string says which:

* **not expressible** -- the real input is not a static field path (an aggregate
  over another model's rows, the live HTTP request, a PostgreSQL sequence). The
  staleness is real but no ``@api.depends`` can fix it.
* **false positive** -- the flagged name is a field name, but the compute reads
  it off something that is not a record (``get_lang(env).code``). See the
  module docstring of ``depends_audit`` for why the static reader cannot tell.
"""

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
    """No computed field may read a model field it declares no dependency on."""

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
        """A stale exemption hides the next regression on that field.

        Once a field is fixed (or removed), its entry must go, otherwise the
        allowlist grows monotonically and stops meaning anything.
        """
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
        """Guard against the audit silently detecting nothing.

        Without this, deleting the body of ``audit_registry`` would leave both
        tests above passing forever. Uses a real registry field and a compute
        that provably reads a sibling.
        """
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
