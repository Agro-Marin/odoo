from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestPartnerAgeRange(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.AgeRange = cls.env["res.partner.age.range"]
        cls.Partner = cls.env["res.partner"]
        cls.AgeRange.search([]).active = False

    def test_01_cohort_bounds_are_validated(self):
        with self.assertRaises(ValidationError):
            self.AgeRange.create(
                {"min_value": 1800, "max_value": 1800, "name": "empty cohort"}
            )
        first = self.AgeRange.create(
            {"min_value": 1800, "max_value": 1806, "name": "cohort A"}
        )
        self.assertEqual(first.min_value, 1800)

        with self.assertRaises(ValidationError):
            self.AgeRange.create({"max_value": 1806, "name": "cohort B"})
        second = self.AgeRange.create({"max_value": 1809, "name": "cohort B"})
        self.assertEqual(
            second.min_value,
            1806,
            "a new cohort must start where the latest existing one ends",
        )

        with self.assertRaises(ValidationError):
            self.AgeRange.create(
                {"min_value": 1807, "max_value": 1810, "name": "cohort C"}
            )
        self.AgeRange.create({"min_value": 1810, "max_value": 1816, "name": "cohort C"})
        with self.assertRaises(ValidationError):
            self.AgeRange.create(
                {"min_value": 1809, "max_value": 1814, "name": "cohort D"}
            )

    def test_02_adjacent_cohorts_do_not_overlap(self):
        self.AgeRange.create({"min_value": 1820, "max_value": 1830, "name": "adj low"})
        self.AgeRange.create({"min_value": 1830, "max_value": 1840, "name": "adj high"})

    def test_03_the_shared_bound_belongs_to_the_later_cohort(self):
        low = self.AgeRange.create(
            {"min_value": 1850, "max_value": 1860, "name": "edge low"}
        )
        high = self.AgeRange.create(
            {"min_value": 1860, "max_value": 1870, "name": "edge high"}
        )
        self.assertFalse(low._covers(1860), "the upper bound is exclusive")
        self.assertTrue(high._covers(1860), "the lower bound is inclusive")

    def test_04_the_cohort_follows_birth_year_not_current_age(self):
        cohort = self.AgeRange.create(
            {"min_value": 1870, "max_value": 1880, "name": "birth-year cohort"}
        )
        january = self.Partner.create(
            {"name": "Born January", "birthdate": "1875-01-01"}
        )
        december = self.Partner.create(
            {"name": "Born December", "birthdate": "1875-12-31"}
        )

        self.assertEqual(january.age_range_id, cohort)
        self.assertEqual(
            december.age_range_id,
            january.age_range_id,
            "two partners born in the same year landed in different cohorts, "
            "so the band is keyed on current age again and will drift every "
            "time one of them has a birthday",
        )

    def test_05_a_partner_without_a_birthdate_carries_no_cohort(self):
        self.AgeRange.create(
            {"min_value": 1890, "max_value": 1900, "name": "unused cohort"}
        )
        partner = self.Partner.create({"name": "No Birthdate Co", "is_company": True})
        self.assertFalse(
            partner.age_range_id,
            "a cohort was assigned with nothing to derive it from",
        )

    def test_06_rebounding_a_cohort_reclassifies_its_partners(self):
        cohort = self.AgeRange.create(
            {"min_value": 1910, "max_value": 1920, "name": "rebound me"}
        )
        partner = self.Partner.create({"name": "Born 1915", "birthdate": "1915-06-01"})
        self.assertEqual(partner.age_range_id, cohort)

        cohort.min_value = 1916
        self.env.flush_all()
        self.assertFalse(
            partner.age_range_id,
            "the cohort no longer covers 1915, but the partner still carries it: "
            "editing the scale left every stored classification stale",
        )

        cohort.min_value = 1910
        self.env.flush_all()
        self.assertEqual(partner.age_range_id, cohort)

    def test_07_archiving_and_deleting_a_cohort_releases_its_partners(self):
        cohort = self.AgeRange.create(
            {"min_value": 1930, "max_value": 1940, "name": "archive me"}
        )
        partner = self.Partner.create({"name": "Born 1935", "birthdate": "1935-06-01"})
        self.assertEqual(partner.age_range_id, cohort)

        cohort.active = False
        self.env.flush_all()
        self.assertFalse(partner.age_range_id, "an archived cohort still classifies")

        cohort.active = True
        self.env.flush_all()
        self.assertEqual(partner.age_range_id, cohort)

        cohort.unlink()
        self.env.flush_all()
        self.assertFalse(partner.age_range_id, "a deleted cohort still classifies")

    def test_08_renaming_a_cohort_does_not_reclassify(self):
        cohort = self.AgeRange.create(
            {"min_value": 1940, "max_value": 1946, "name": "rename me"}
        )
        partner = self.Partner.create({"name": "Born 1942", "birthdate": "1942-06-01"})
        self.assertEqual(partner.age_range_id, cohort)

        cohort.name = "renamed"
        self.env.flush_all()
        self.assertEqual(partner.age_range_id, cohort)

    def test_09_an_open_ended_cohort_still_reclassifies(self):
        cohort = self.AgeRange.create(
            {"min_value": 2200, "max_value": 0, "name": "open ended"}
        )
        partner = self.Partner.create({"name": "Born 2400", "birthdate": "2400-06-01"})
        self.assertEqual(partner.age_range_id, cohort)

        cohort.min_value = 2500
        self.env.flush_all()
        self.assertFalse(
            partner.age_range_id,
            "max_value 0 means unbounded, so the sweep must reach a birth year "
            "with no upper bound above it",
        )

    def test_10_a_cohort_open_on_its_lower_side_still_reclassifies(self):
        cohort = self.AgeRange.create(
            {"min_value": 0, "max_value": 1600, "name": "open below"}
        )
        partner = self.Partner.create({"name": "Born 1500", "birthdate": "1500-06-01"})
        self.assertEqual(partner.age_range_id, cohort)

        cohort.max_value = 1450
        self.env.flush_all()
        self.assertFalse(
            partner.age_range_id,
            "min_value 0 is no lower bound at all -- year 0 is not a date, and "
            "treating it as one would drop the whole span from the sweep",
        )

    def test_11_a_drifted_partner_is_repaired_by_touching_its_own_band(self):
        cohort = self.AgeRange.create(
            {"min_value": 1700, "max_value": 1710, "name": "drift home"}
        )
        stranger = self.Partner.create(
            {"name": "Born 1850 elsewhere", "birthdate": "1850-06-01"}
        )
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE res_partner SET age_range_id = %s WHERE id = %s",
            (cohort.id, stranger.id),
        )
        self.env.invalidate_all()
        self.assertEqual(stranger.age_range_id, cohort, "fixture did not take")

        cohort.max_value = 1711
        self.env.flush_all()
        self.assertFalse(
            stranger.age_range_id,
            "a partner pointing at the edited band must be swept even though "
            "its birth year lies outside every bound the write moved",
        )

    def test_12_an_untouched_span_is_not_swept(self):
        near = self.AgeRange.create(
            {"min_value": 1750, "max_value": 1760, "name": "near"}
        )
        far = self.AgeRange.create(
            {"min_value": 1770, "max_value": 1780, "name": "far"}
        )
        stranger = self.Partner.create({"name": "Born 1775", "birthdate": "1775-06-01"})
        self.assertEqual(stranger.age_range_id, far)

        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE res_partner SET age_range_id = NULL WHERE id = %s", (stranger.id,)
        )
        self.env.invalidate_all()

        near.max_value = 1761
        self.env.flush_all()
        self.assertFalse(
            stranger.age_range_id,
            "editing a band 15 years away re-derived a partner it cannot "
            "reclassify, so the sweep is no longer narrowed",
        )

        far.max_value = 1781
        self.env.flush_all()
        self.assertEqual(far, stranger.age_range_id, "its own band must repair it")

    def test_13_an_archived_partner_is_reclassified_like_any_other(self):
        cohort = self.AgeRange.create(
            {"min_value": 1960, "max_value": 1970, "name": "archived member"}
        )
        partner = self.Partner.create({"name": "Born 1965", "birthdate": "1965-06-01"})
        self.assertEqual(partner.age_range_id, cohort)

        partner.active = False
        cohort.min_value = 1966
        self.env.flush_all()
        partner.invalidate_recordset(["age_range_id"])
        self.assertFalse(
            partner.age_range_id,
            "the sweep searched res.partner with the default active_test, so an "
            "archived partner kept a cohort whose bounds no longer reach it",
        )

        cohort.min_value = 1960
        self.env.flush_all()
        partner.invalidate_recordset(["age_range_id"])
        self.assertEqual(
            partner.age_range_id, cohort, "an archived partner must also be re-covered"
        )

    def test_14_a_new_cohort_chains_onto_the_highest_closed_bound(self):
        self.assertEqual(
            self.AgeRange.default_get(["min_value"])["min_value"],
            0.0,
            "with no cohorts at all there is nothing to chain onto",
        )
        self.AgeRange.create({"min_value": 1500, "max_value": 1600, "name": "closed"})
        self.assertEqual(self.AgeRange.default_get(["min_value"])["min_value"], 1600)

        self.AgeRange.create({"min_value": 1600, "max_value": 0, "name": "open top"})
        self.assertEqual(
            self.AgeRange.default_get(["min_value"])["min_value"],
            1600,
            "the open cohort's max_value of 0 means no upper limit; chaining "
            "onto it would propose 0 as a LOWER bound, which means the opposite",
        )

    def test_15_a_cohort_name_is_unique_regardless_of_casing(self):
        """UNIQUE(name) let "Baby boomer" and "baby boomer" both exist.

        The rule is a unique index over lower(name) rather than a constraint,
        which is a conversion the framework refused to perform until
        2c60f5f3d33: it left the old constraint in force and the database
        unupgradable afterwards.
        """
        self.AgeRange.create({"min_value": 1400, "max_value": 1410, "name": "Casing"})
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self.AgeRange.create(
                    {"min_value": 1410, "max_value": 1420, "name": "casing"}
                )

    def test_16_an_overlap_inside_one_batch_is_still_rejected(self):
        """The scale is searched once for the batch, so the batch's own members
        have to be compared in memory or two overlapping cohorts created
        together would both pass."""
        with self.assertRaises(ValidationError):
            self.AgeRange.create(
                [
                    {"name": "batch a", "min_value": 1200, "max_value": 1210},
                    {"name": "batch b", "min_value": 1205, "max_value": 1215},
                ]
            )

    def test_17_checking_a_scale_does_not_cost_a_query_per_band(self):
        """`_check_band` ran one sibling search per record, from a constraint.

        The assertion is on scaling rather than on a number: what matters is
        that a wider batch does not buy more queries, and an exact count would
        pin every incidental search the create path happens to make today.
        """
        AgeRange = type(self.AgeRange)
        original = AgeRange.search
        counted = []

        def counting_search(records, domain, *args, **kwargs):
            counted.append(domain)
            return original(records, domain, *args, **kwargs)

        def searches_for(count, first_year):
            counted.clear()
            with patch.object(AgeRange, "search", counting_search):
                self.AgeRange.create(
                    [
                        {
                            "name": f"scale {first_year} {index}",
                            "min_value": first_year + index * 10,
                            "max_value": first_year + index * 10 + 10,
                        }
                        for index in range(count)
                    ]
                )
                self.env.flush_all()
            return len(counted)

        few = searches_for(3, 2600)
        many = searches_for(12, 2700)

        self.assertEqual(
            few,
            many,
            f"{few} searches for 3 bands and {many} for 12: the sibling lookup "
            "still scales with the size of the batch",
        )
