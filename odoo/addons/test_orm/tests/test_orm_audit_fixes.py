"""DB-tier regression tests for the ORM audit fixes.

Covers:

- deprecated ``read_group()`` with ``groupby=[]`` and a dict ``fill_temporal``
  context (used to crash with IndexError), and unknown ``fill_temporal`` keys
  (used to crash with TypeError on ``**``-unpacking);
- ``_read_group_having`` under-arity domains raising ``ValueError`` end-to-end
  through the public ``formatted_read_group(having=...)``;
- field-level access checks on the empty-query shortcut of ``_read_group`` /
  ``_read_grouping_sets`` (must match the non-empty path);
- ``_ensure_xml_ids`` determinism (oldest xmlid wins, agreeing with
  ``get_metadata``);
- ``with_company()`` rejecting unsaved (NewId) companies;
- ``_search_display_name`` no longer propagating TypeError for unconvertible
  scalar values;
- ``copy_translations`` refusing to positionally misalign one2many lines when
  ``copy_data`` dropped some of them (loud skip instead).
"""

import warnings

from odoo.exceptions import AccessError
from odoo.fields import Command, Domain
from odoo.tests.common import TransactionCase, new_test_user


class TestReadGroupAuditFixes(TransactionCase):
    def _read_group_deprecated(self, model, domain, fields, groupby, **kwargs):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            return model.read_group(domain, fields, groupby, **kwargs)

    def test_read_group_empty_groupby_with_dict_fill_temporal(self):
        """groupby=[] + dict fill_temporal used to crash with IndexError."""
        model = self.env["test_orm.lesson"].with_context(fill_temporal={})
        rows = self._read_group_deprecated(model, [], ["__count"], [])
        self.assertEqual(len(rows), 1)
        self.assertIn("__count", rows[0])

    def test_read_group_fill_temporal_unknown_keys_ignored(self):
        """Unknown fill_temporal keys used to TypeError on **-unpacking."""
        lessons = self.env["test_orm.lesson"].create(
            [
                {"name": "jan", "date": "2024-01-15"},
                {"name": "mar", "date": "2024-03-15"},
            ]
        )
        model = self.env["test_orm.lesson"].with_context(
            fill_temporal={
                "fill_from": "2024-01-01",
                "fill_to": "2024-04-30",
                "bogus_key": 42,
            }
        )
        rows = self._read_group_deprecated(
            model, [("id", "in", lessons.ids)], ["__count"], ["date:month"]
        )
        self.assertEqual(len(rows), 4)

    def test_read_group_range_accumulates_across_temporal_groupbys(self):
        """``__range`` is keyed BY GROUP and must survive a date *property*.

        ``_read_group_format_result`` writes the date/datetime branch with
        ``row.setdefault("__range", {})[group] = ...`` (accumulating), but
        ``_read_group_format_result_properties`` assigned a fresh dict
        (``row["__range"] = {group: ...}`` / ``= {}``). Grouping by a real date
        field *and* a date property in one request therefore dropped the date
        field's entry from every row -- and the null-property row lost
        ``__range`` entirely. The web client reads ``__range`` to build the
        date-range drill-down domain, so the entry silently going missing breaks
        navigation rather than raising.
        """
        discussion = self.env["test_orm.discussion"].create(
            {
                "name": "range accumulation",
                "participants": [Command.set([self.env.user.id])],
                "attributes_definition": [
                    {"name": "pdate", "type": "date", "string": "P Date"},
                ],
            }
        )
        Message = self.env["test_orm.message"]
        Message.create(
            [
                {
                    "discussion": discussion.id,
                    "name": "m1",
                    "attributes": {"pdate": "2024-03-10"},
                },
                {
                    "discussion": discussion.id,
                    "name": "m2",
                    "attributes": {"pdate": "2024-05-20"},
                },
                {
                    "discussion": discussion.id,
                    "name": "m3",
                    "attributes": {"pdate": False},
                },
            ]
        )
        rows = self._read_group_deprecated(
            Message.with_context(active_test=False),
            [("discussion", "=", discussion.id)],
            [],
            ["create_date:month", "attributes.pdate:month"],
            lazy=False,
        )
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertIn(
                "create_date:month",
                row["__range"],
                "the date field's __range entry was dropped by the property group",
            )
            self.assertIn("attributes.pdate:month", row["__range"])

    def test_formatted_read_group_malformed_having_raises_valueerror(self):
        model = self.env["test_orm.lesson"]
        model.create({"name": "l"})
        for having in (
            ["|", ("__count", ">", 1)],
            ["&"],
            ["!"],
        ):
            with (
                self.subTest(having=having),
                self.assertRaisesRegex(ValueError, "Invalid having clause"),
            ):
                model.formatted_read_group([], [], ["__count"], having=having)
        result = model.formatted_read_group(
            [], [], ["__count"], having=[("__count", ">", 0)]
        )
        self.assertTrue(result)

    def test_read_group_empty_query_checks_field_access(self):
        """The empty-query shortcut must apply the same field-level checks as
        the non-empty path (cf. search_fetch's empty path)."""
        user = new_test_user(self.env, "audit_fix_user")
        course = self.env["test_orm.course"].with_user(user)
        empty_domain = [("id", "in", [])]

        with self.assertRaises(AccessError):
            course._read_group([], ["private_field"], ["__count"])

        with self.assertRaises(AccessError):
            course._read_group(empty_domain, ["private_field"], ["__count"])
        with self.assertRaises(AccessError):
            course._read_group(empty_domain, [], ["private_field:count"])
        with self.assertRaises(AccessError):
            course._read_grouping_sets(
                empty_domain, [["private_field"], []], ["__count"]
            )
        with self.assertRaises(ValueError):
            course._read_group(empty_domain, ["nonexistent_field"], [])
        with self.assertRaises(ValueError):
            course._read_group(empty_domain, [], ["name:bogus_agg"])

        self.assertEqual(course._read_group(empty_domain, ["name"], ["__count"]), [])
        self.assertEqual(
            course._read_group(empty_domain, [], ["__count"]),
            [(0,)],
        )


class TestExportXidDeterminism(TransactionCase):
    def test_ensure_xml_ids_oldest_wins_and_matches_get_metadata(self):
        record = self.env["test_orm.lesson"].create({"name": "xid lesson"})
        imd = self.env["ir.model.data"]
        first = imd.create(
            {
                "module": "__export__",
                "name": "audit_xid_first",
                "model": record._name,
                "res_id": record.id,
            }
        )
        second = imd.create(
            {
                "module": "__export__",
                "name": "audit_xid_second",
                "model": record._name,
                "res_id": record.id,
            }
        )
        self.assertLess(first.id, second.id)

        [(rec, xid)] = list(record._ensure_xml_ids())
        self.assertEqual(rec, record)
        self.assertEqual(xid, "__export__.audit_xid_first")
        self.assertEqual(
            record.get_metadata()[0]["xmlid"], "__export__.audit_xid_first"
        )


class TestWithCompanyNewId(TransactionCase):
    def test_with_company_unsaved_company_raises(self):
        model = self.env["test_orm.lesson"]
        ghost = self.env["res.company"].new({"name": "Ghost Co"})
        with self.assertRaisesRegex(ValueError, "saved .real-id. company"):
            model.with_company(ghost)
        self.assertIs(model.with_company(None), model)
        self.assertIs(model.with_company(self.env["res.company"].browse()), model)
        result = model.with_company(self.env.company)
        self.assertEqual(result.env.company, self.env.company)


class TestSearchDisplayNameRobustness(TransactionCase):
    def test_unconvertible_scalar_value_does_not_raise(self):
        model = self.env["test_orm.lesson"]
        self.patch(self.registry["test_orm.lesson"], "_rec_names_search", ["date"])
        domain = model._search_display_name("=", object())
        self.assertTrue(Domain(domain).is_false())


class TestCopyTranslationsAlignment(TransactionCase):
    def test_copy_translations_skips_on_o2m_length_mismatch(self):
        """When old/new one2many lines cannot be paired positionally, the
        translation copy for that field is skipped loudly, never misaligned."""
        Discussion = self.env["test_orm.discussion"]
        participants = [Command.link(self.env.user.id)]
        old = Discussion.create(
            {
                "name": "old",
                "participants": participants,
                "messages": [
                    Command.create({"body": "first"}),
                    Command.create({"body": "second"}),
                ],
            }
        )
        new = Discussion.create(
            {
                "name": "new",
                "participants": participants,
                "messages": [Command.create({"body": "first"})],
            }
        )
        with self.assertLogs("odoo.models", level="DEBUG") as capture:
            old.copy_translations(new)
        self.assertTrue(
            any(
                "skipping one2many field 'messages'" in line for line in capture.output
            ),
            capture.output,
        )

    def test_copy_translations_aligned_lines_still_copied(self):
        self.env["res.lang"]._activate_lang("fr_FR")
        Discussion = self.env["test_orm.discussion"]
        old = Discussion.create(
            {
                "name": "old",
                "participants": [Command.link(self.env.user.id)],
                "messages": [
                    Command.create({"body": "b1", "label": "Label A"}),
                    Command.create({"body": "b2", "label": "Label B"}),
                ],
            }
        )
        old.messages.sorted(key="id")[0].with_context(
            lang="fr_FR"
        ).label = "Etiquette A"
        copied = old.copy()
        copied_lines = copied.messages.sorted(key="id")
        self.assertEqual(len(copied_lines), 2)
        self.assertEqual(
            copied_lines[0].with_context(lang="fr_FR").label, "Etiquette A"
        )
