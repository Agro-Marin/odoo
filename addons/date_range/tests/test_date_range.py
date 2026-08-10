import datetime

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase


class DateRangeTest(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.date_range = cls.env["date.range"]
        cls.type = cls.env["date.range.type"].create(
            {"name": "Fiscal year", "company_id": False, "allow_overlap": False}
        )
        cls.company = cls.env["res.company"].create({"name": "Test company"})
        cls.company_2 = cls.env["res.company"].create(
            {"name": "Test company 2", "parent_id": cls.company.id}
        )
        cls.type_b = cls.env["date.range.type"].create(
            {
                "name": "Fiscal year B",
                "company_id": cls.company.id,
                "allow_overlap": False,
            }
        )

    def test_default_company(self):
        dr = self.date_range.create(
            {
                "name": "FS2016",
                "date_start": "2015-01-01",
                "date_end": "2016-12-31",
                "type_id": self.type.id,
            }
        )
        self.assertTrue(dr.company_id)
        # you can specify company_id to False
        dr = self.date_range.create(
            {
                "name": "FS2016_NO_COMPANY",
                "date_start": "2015-01-01",
                "date_end": "2016-12-31",
                "type_id": self.type.id,
                "company_id": False,
            }
        )
        self.assertFalse(dr.company_id)

    def test_empty_company(self):
        dr = self.date_range.create(
            {
                "name": "FS2016",
                "date_start": "2015-01-01",
                "date_end": "2016-12-31",
                "type_id": self.type.id,
                "company_id": None,
            }
        )
        self.assertEqual(dr.name, "FS2016")

    def test_invalid(self):
        with self.assertRaises(ValidationError) as cm:
            self.date_range.create(
                {
                    "name": "FS2016",
                    "date_end": "2015-01-01",
                    "date_start": "2016-12-31",
                    "type_id": self.type.id,
                }
            )
        message = str(cm.exception.args[0])
        self.assertEqual(
            message, "FS2016 is not a valid range (2016-12-31 > 2015-01-01)"
        )

    def test_overlap(self):
        self.date_range.create(
            {
                "name": "FS2015",
                "date_start": "2015-01-01",
                "date_end": "2015-12-31",
                "type_id": self.type.id,
            }
        )
        with self.assertRaises(ValidationError) as cm, self.env.cr.savepoint():
            self.date_range.create(
                {
                    "name": "FS2016",
                    "date_start": "2015-01-01",
                    "date_end": "2016-12-31",
                    "type_id": self.type.id,
                }
            )
        message = str(cm.exception.args[0])
        self.assertEqual(message, "FS2016 overlaps FS2015")
        # check it's possible to overlap if it's allowed by the date range type
        self.type.allow_overlap = True
        dr = self.date_range.create(
            {
                "name": "FS2016",
                "date_start": "2015-01-01",
                "date_end": "2016-12-31",
                "type_id": self.type.id,
            }
        )
        self.assertEqual(dr.name, "FS2016")

    def test_overlap_without_intervening_flush(self):
        """Two overlapping ranges written before any flush are still caught.

        ``active`` is written during the flush that follows the constraint, so
        a check reading the table sees NULL for a sibling created moments
        earlier. This used to switch the whole guard off.
        """
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.date_range.create(
                {
                    "name": "A",
                    "date_start": "2040-01-01",
                    "date_end": "2040-12-31",
                    "type_id": self.type.id,
                }
            )
            self.date_range.create(
                {
                    "name": "B",
                    "date_start": "2040-06-01",
                    "date_end": "2041-06-30",
                    "type_id": self.type.id,
                }
            )
            self.env.flush_all()

    def test_overlap_in_a_single_batch(self):
        """The same two ranges created in one call are caught too."""
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.date_range.create(
                [
                    {
                        "name": "A",
                        "date_start": "2041-01-01",
                        "date_end": "2041-12-31",
                        "type_id": self.type.id,
                    },
                    {
                        "name": "B",
                        "date_start": "2041-06-01",
                        "date_end": "2042-06-30",
                        "type_id": self.type.id,
                    },
                ]
            )
            self.env.flush_all()

    def test_overlap_without_company(self):
        """Company-less ranges are checked like any other.

        ``company_id = NULL`` is never true in SQL, so comparing with ``=``
        exempted every company-less range — which is all of them in the shipped
        data files.
        """
        self.date_range.create(
            {
                "name": "NC1",
                "date_start": "2042-01-01",
                "date_end": "2042-12-31",
                "type_id": self.type.id,
                "company_id": False,
            }
        )
        self.env.flush_all()
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.date_range.create(
                {
                    "name": "NC2",
                    "date_start": "2042-06-01",
                    "date_end": "2043-06-30",
                    "type_id": self.type.id,
                    "company_id": False,
                }
            )
            self.env.flush_all()

    def test_sub_range_may_span_its_parent(self):
        """Overlap is checked between siblings, not against the parent."""
        parent = self.date_range.create(
            {
                "name": "P",
                "date_start": "2043-01-01",
                "date_end": "2043-12-31",
                "type_id": self.type.id,
            }
        )
        children = self.date_range.create(
            [
                {
                    "name": "P-H1",
                    "date_start": "2043-01-01",
                    "date_end": "2043-06-30",
                    "type_id": self.type.id,
                    "parent_id": parent.id,
                },
                {
                    "name": "P-H2",
                    "date_start": "2043-07-01",
                    "date_end": "2043-12-31",
                    "type_id": self.type.id,
                    "parent_id": parent.id,
                },
            ]
        )
        self.env.flush_all()
        self.assertEqual(children.parent_id, parent)
        self.assertTrue(all(children.mapped("is_sub_range")))
        # siblings still may not overlap each other
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.date_range.create(
                {
                    "name": "P-overlapping",
                    "date_start": "2043-06-01",
                    "date_end": "2043-08-31",
                    "type_id": self.type.id,
                    "parent_id": parent.id,
                }
            )
            self.env.flush_all()

    def test_split_by(self):
        parent = self.date_range.create(
            {
                "name": "Q",
                "date_start": "2044-01-01",
                "date_end": "2044-03-31",
                "type_id": self.type.id,
            }
        )
        vals = parent.split_by("month")
        self.assertEqual(len(vals), 3)
        children = self.date_range.create(vals)
        self.env.flush_all()
        self.assertEqual(children.mapped("date_start")[0], datetime.date(2044, 1, 1))
        self.assertEqual(children.mapped("date_end")[-1], datetime.date(2044, 3, 31))
        self.assertEqual(children.parent_id, parent)
        weeks = parent.split_by("week")
        self.assertEqual(weeks[0]["date_end"], datetime.date(2044, 1, 3))
        with self.assertRaises(ValueError):
            parent.split_by("fortnight")

    def test_unique_name_survives_translation(self):
        """A translated name does not create a second identity."""
        self.env["res.lang"]._activate_lang("es_MX")
        first = self.date_range.create(
            {
                "name": "Season A",
                "date_start": "2045-01-01",
                "date_end": "2045-01-31",
                "type_id": self.type.id,
            }
        )
        first.with_context(lang="es_MX").name = "Temporada A"
        self.env.flush_all()
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.date_range.create(
                {
                    "name": "Season A",
                    "date_start": "2046-01-01",
                    "date_end": "2046-01-31",
                    "type_id": self.type.id,
                }
            )
            self.env.flush_all()

    def test_archive_survives_type_restore(self):
        """Archiving a type archives its ranges; restoring it does not undo that."""
        dr_type = self.env["date.range.type"].create(
            {"name": "Archivable", "allow_overlap": True}
        )
        keep, archived = self.date_range.create(
            [
                {
                    "name": "keep",
                    "date_start": "2047-01-01",
                    "date_end": "2047-01-31",
                    "type_id": dr_type.id,
                },
                {
                    "name": "archived-by-hand",
                    "date_start": "2047-02-01",
                    "date_end": "2047-02-28",
                    "type_id": dr_type.id,
                },
            ]
        )
        archived.active = False
        self.env.flush_all()
        dr_type.active = False
        self.env.flush_all()
        self.assertFalse(keep.active)
        dr_type.active = True
        self.env.flush_all()
        self.assertFalse(keep.active, "restoring a type must not resurrect ranges")
        self.assertFalse(archived.active)

    def test_duration_and_business_days(self):
        # 2044-01-04 is a Monday; through Sunday 2044-01-17 is exactly two weeks
        dr = self.date_range.create(
            {
                "name": "Two weeks",
                "date_start": "2044-01-04",
                "date_end": "2044-01-17",
                "type_id": self.type.id,
            }
        )
        self.assertEqual(dr.duration_days, 14)
        self.assertEqual(dr.business_days, 10)
        self.assertEqual(dr.weekend_days, 4)
        # a single Saturday
        dr = self.date_range.create(
            {
                "name": "One Saturday",
                "date_start": "2044-01-23",
                "date_end": "2044-01-23",
                "type_id": self.type.id,
            }
        )
        self.assertEqual(dr.duration_days, 1)
        self.assertEqual(dr.business_days, 0)
        self.assertEqual(dr.weekend_days, 1)

    def test_domain(self):
        dr = self.date_range.create(
            {
                "name": "FS2015",
                "date_start": "2015-01-01",
                "date_end": "2015-12-31",
                "type_id": self.type.id,
            }
        )
        domain = dr.get_domain("my_field")
        # Bounds are inclusive; the upper one comes first so the backend domain
        # editor recognises the pair as a period.
        self.assertEqual(
            domain,
            [
                ("my_field", "<=", datetime.date(2015, 12, 31)),
                ("my_field", ">=", datetime.date(2015, 1, 1)),
            ],
        )

    def test_navigation_helpers(self):
        dr_type = self.env["date.range.type"].create(
            {"name": "Quarters", "allow_overlap": False}
        )
        q1, q2, q3 = self.date_range.create(
            [
                {
                    "name": "2048 Q1",
                    "date_start": "2048-01-01",
                    "date_end": "2048-03-31",
                    "type_id": dr_type.id,
                },
                {
                    "name": "2048 Q2",
                    "date_start": "2048-04-01",
                    "date_end": "2048-06-30",
                    "type_id": dr_type.id,
                },
                {
                    "name": "2048 Q3",
                    "date_start": "2048-07-01",
                    "date_end": "2048-09-30",
                    "type_id": dr_type.id,
                },
            ]
        )
        self.env.flush_all()
        self.assertEqual(q2.get_next_range(), q3)
        self.assertEqual(q2.get_previous_range(), q1)
        self.assertFalse(q3.get_next_range())
        current = self.date_range.get_current_range(
            date=datetime.date(2048, 5, 15), type_id=dr_type
        )
        self.assertEqual(current, q2)
        self.assertFalse(
            self.date_range.get_current_range(
                date=datetime.date(2049, 5, 15), type_id=dr_type
            )
        )

    def test_get_current_range_scopes_to_company(self):
        dr_type = self.env["date.range.type"].create(
            {"name": "Scoped", "company_id": False, "allow_overlap": True}
        )
        other = self.date_range.create(
            {
                "name": "Other company period",
                "date_start": "2050-01-01",
                "date_end": "2050-12-31",
                "type_id": dr_type.id,
                "company_id": self.company.id,
            }
        )
        self.env.flush_all()
        self.assertFalse(
            self.date_range.get_current_range(
                date=datetime.date(2050, 6, 1), type_id=dr_type
            )
        )
        self.assertEqual(
            self.date_range.get_current_range(
                date=datetime.date(2050, 6, 1),
                type_id=dr_type,
                company_id=self.company.id,
            ),
            other,
        )

    def test_date_range_multicompany_1(self):
        with self.assertRaises(UserError):
            self.date_range.create(
                {
                    "name": "FS2016",
                    "date_start": "2015-01-01",
                    "date_end": "2016-12-31",
                    "type_id": self.type_b.id,
                    "company_id": self.company_2.id,
                }
            )
