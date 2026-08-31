from odoo.tests.common import TransactionCase, tagged


class TestPartnerDependsCompleteness(TransactionCase):
    def test_partner_computes_declare_what_they_read(self):
        parent = self.env["res.partner"].create(
            {"name": "Acme Corp", "is_company": True}
        )
        child = self.env["res.partner"].create(
            {
                "name": "Jane",
                "parent_id": parent.id,
                "street": "Main 1",
                "city": "Town",
            }
        )
        self.assertDependsComplete(parent + child)


class TestCurrencyDependsCompleteness(TransactionCase):
    def test_currency_computes_declare_what_they_read(self):
        currencies = (
            self.env["res.currency"].with_context(active_test=False).search([], limit=3)
        )
        self.assertDependsComplete(
            currencies,
            known_incomplete=["rate_string"],
        )

    def test_rate_string_follows_its_own_currency_code(self):
        company_currency = self.env.company.currency_id
        other = (
            self.env["res.currency"]
            .with_context(active_test=False)
            .search([("id", "!=", company_currency.id)], limit=1)
        )
        self.assertTrue(other, "need a currency other than the company's")
        self.env.flush_all()
        self.env.invalidate_all()
        other.rate_string
        other.write({"name": "ZZZ"})
        cached = self.env["res.currency"].browse(other.id).rate_string
        self.env.flush_all()
        self.env.invalidate_all()
        fresh = self.env["res.currency"].browse(other.id).rate_string
        self.assertEqual(cached, fresh, "renaming a currency left rate_string stale")


SWEEP_EXEMPT: dict[str, str] = {
    "res.currency.rate_string": (
        "renders the *company's* currency code, chosen from the company or the "
        "context; no path from res.currency reaches another currency's name"
    ),
    "account.journal.kanban_dashboard": (
        "aggregates rows of account.move and account.payment; no static field "
        "path from account.journal reaches a row count of another model"
    ),
}


@tagged("-standard", "depends_sweep")
class TestDependsSweep(TransactionCase):
    def _sweepable_models(self, unreadable: list[str]):
        for model_name in sorted(self.env.registry):
            model = self.env[model_name].sudo()
            if model._abstract or model._transient or not model._auto:
                continue
            if not any(f.compute and not f.related for f in model._fields.values()):
                continue
            try:
                records = model.with_context(active_test=False).search([], limit=3)
            except Exception as exc:
                unreadable.append(f"{model_name}: {type(exc).__name__}: {exc}"[:200])
                continue
            if len(records) >= 2:
                yield model_name, records

    def test_every_installed_model_declares_what_its_computes_read(self):
        found: dict[str, tuple] = {}
        unreadable: list[str] = []
        for _model_name, records in self._sweepable_models(unreadable):
            savepoint = self.env.cr.savepoint(flush=False)
            try:
                stale = self.findStaleComputedFields(records)
            finally:
                savepoint.rollback()
                savepoint.close(rollback=False)
                self.env.clear()
            for _probe, field_name, value, cached, fresh in stale:
                label = f"{records._name}.{field_name}"
                found.setdefault(label, (value, cached, fresh))

        unexpected = {k: v for k, v in found.items() if k not in SWEEP_EXEMPT}
        self.assertFalse(
            unexpected,
            "computed field(s) held a value the database no longer agreed with, "
            "after a write to a field they do not depend on:\n"
            + "\n".join(
                f"  {label} after writing {value!r}\n"
                f"      cached {cached!r}\n"
                f"      fresh  {fresh!r}"
                for label, (value, cached, fresh) in sorted(unexpected.items())
            )
            + "\n\nDeclare the dependency with @api.depends, or -- if the real "
            f"input is not a static field path -- add it to SWEEP_EXEMPT in {__file__}.",
        )
        self.assertFalse(
            unreadable,
            "these models could not be searched, so the sweep never probed "
            "them and covers less than it reports:\n  " + "\n  ".join(unreadable),
        )
        self.addCleanup(self._assert_exemptions_still_needed, set(found))

    def _assert_exemptions_still_needed(self, found: set[str]) -> None:
        installed = {
            label
            for label in SWEEP_EXEMPT
            if (model_name := label.rsplit(".", 1)[0]) in self.env
            and label.rsplit(".", 1)[1] in self.env[model_name]._fields
        }
        self.assertFalse(
            sorted(installed - found),
            f"these SWEEP_EXEMPT entries no longer go stale; delete them from "
            f"{__file__}: {sorted(installed - found)}",
        )

    def test_the_sweep_can_detect_a_deliberately_broken_field(self):
        Partner = self.env["res.partner"]
        parent = Partner.create({"name": "Sensitivity parent", "is_company": True})
        other = Partner.create({"name": "Sensitivity other", "is_company": True})
        child = Partner.create({"name": "Sensitivity child", "parent_id": parent.id})

        registry = self.env.registry
        field = Partner._fields["commercial_partner_id"]
        original = registry.field_depends.get(field, ())
        stripped = tuple(p for p in original if not p.startswith("parent_id"))
        self.assertNotEqual(
            original, stripped, "the fixture assumes a parent_id dependency"
        )
        try:
            registry.field_depends[field] = stripped
            registry.__dict__.pop("_field_triggers", None)
            registry.model_graph.reset_triggers()
            registry._get_field_triggers()
            self.env.invalidate_all()
            stale = self.findStaleComputedFields(
                child + other,
                computed_fields=["commercial_partner_id"],
                probe_fields=["parent_id"],
            )
        finally:
            registry.field_depends[field] = original
            registry.__dict__.pop("_field_triggers", None)
            registry.model_graph.reset_triggers()
            registry._get_field_triggers()
            self.env.invalidate_all()

        self.assertTrue(
            stale,
            "the sweep did not notice a dependency removed from under it, so a "
            "clean sweep proves nothing about many2one-reached dependencies",
        )
