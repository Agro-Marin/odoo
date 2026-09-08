from psycopg.errors import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import PartnerRelationCommon


@tagged("post_install", "-at_install")
class TestPartnerRelation(PartnerRelationCommon):
    def test_gendered_wording_follows_each_end(self):
        relation = self._create_relation(self.juan, self.type_parent, self.lucia)

        self.assertEqual(relation.label, "father of")
        self.assertEqual(relation.label_inverse, "daughter of")

    def test_neutral_wording_when_gender_is_unknown(self):
        anonymous = self.env["res.partner"].create({"name": "Anonymous"})

        relation = self._create_relation(anonymous, self.type_parent, self.lucia)

        self.assertEqual(relation.label, "parent of")

    def test_a_symmetric_type_reads_the_same_from_both_ends(self):
        relation = self._create_relation(self.juan, self.type_sibling, self.pedro)

        self.assertEqual(relation.label, "brother of")
        self.assertEqual(relation.label_inverse, "brother of")

    def test_compadre_and_comadre_are_one_type(self):
        of_juan = self._create_relation(self.juan, self.type_compadre, self.pedro)
        of_maria = self._create_relation(self.maria, self.type_compadre, self.lucia)

        self.assertEqual(of_juan.label, "compadre of")
        self.assertEqual(of_maria.label, "comadre of")
        self.assertEqual(of_juan.type_id, of_maria.type_id)

    def test_a_record_being_composed_has_no_wording_yet(self):
        # The form computes both labels on its first onchange, before the user
        # has reached the required Relationship field.
        relation = self.relations.new({"partner_id": self.juan.id})

        self.assertFalse(relation.label)
        self.assertFalse(relation.label_inverse)
        self.assertNotIn("False", relation.display_name)

    def test_a_symmetric_relation_may_not_be_stored_twice(self):
        self._create_relation(self.juan, self.type_spouse, self.maria)

        with self.assertRaises(ValidationError):
            self._create_relation(self.maria, self.type_spouse, self.juan)

    def test_an_impossible_kinship_mirror_is_refused(self):
        self._create_relation(self.juan, self.type_parent, self.lucia)

        with self.assertRaises(ValidationError):
            self._create_relation(self.lucia, self.type_parent, self.juan)

    def test_a_genuinely_mutual_tie_may_be_recorded_both_ways(self):
        self._create_relation(self.juan, self.type_guarantor, self.pedro)

        mirrored = self._create_relation(self.pedro, self.type_guarantor, self.juan)

        self.assertTrue(mirrored)
        self.assertFalse(self.type_guarantor.is_antisymmetric)

    def test_a_type_may_not_be_both_symmetric_and_antisymmetric(self):
        with self.assertRaises(ValidationError):
            self.env["res.partner.relation.type"].create(
                {
                    "code": "test_contradiction",
                    "name": "both ways at once",
                    "name_inverse": "and not",
                    "category": "business",
                    "is_symmetric": True,
                    "is_antisymmetric": True,
                }
            )

    def test_a_contact_may_not_be_related_to_itself(self):
        with self.assertRaises(IntegrityError), mute_logger("odoo.db.cursor"):
            self._create_relation(self.juan, self.type_sibling, self.juan)
            self.env.flush_all()

    def test_the_same_relation_may_not_be_recorded_twice(self):
        self._create_relation(self.juan, self.type_parent, self.lucia)

        with self.assertRaises(IntegrityError), mute_logger("odoo.db.cursor"):
            self._create_relation(self.juan, self.type_parent, self.lucia)
            self.env.flush_all()

    def test_an_end_date_before_the_start_is_refused(self):
        relation = self._create_relation(self.juan, self.type_spouse, self.maria)

        with self.assertRaises(ValidationError):
            relation.write({"date_start": "2020-01-01", "date_end": "2019-01-01"})

    def test_swapping_rewords_the_relation(self):
        relation = self._create_relation(self.juan, self.type_parent, self.lucia)

        relation.action_swap()

        self.assertEqual(relation.partner_id, self.lucia)
        self.assertEqual(relation.label, "mother of")

    def test_the_type_carries_the_risk_weight_onto_the_relation(self):
        relation = self._create_relation(self.juan, self.type_spouse, self.maria)

        self.assertEqual(relation.weight_risk, self.type_spouse.weight_risk)
        self.assertEqual(relation.category, "affinity")

    def test_ritual_kinship_carries_no_genealogical_distance(self):
        self.assertEqual(self.type_compadre.category, "ritual")
        self.assertEqual(self.type_compadre.degree, 0)
        self.assertGreater(self.type_compadre.weight_risk, 0)

    def test_an_asymmetric_type_needs_wording_for_its_other_end(self):
        with self.assertRaises(ValidationError):
            self.env["res.partner.relation.type"].create(
                {
                    "code": "test_incomplete",
                    "name": "landlord of",
                    "category": "business",
                }
            )

    def test_a_relation_is_found_by_the_name_of_either_contact(self):
        relation = self._create_relation(self.juan, self.type_spouse, self.maria)

        found_ids = [found for found, _name in self.relations.name_search("Maria")]

        self.assertIn(relation.id, found_ids)

    def test_an_archived_mirror_may_not_be_brought_back_beside_its_twin(self):
        original = self._create_relation(self.juan, self.type_spouse, self.maria)
        original.active = False
        self._create_relation(self.maria, self.type_spouse, self.juan)

        with self.assertRaises(ValidationError):
            original.active = True

    def test_rewording_a_type_rewords_its_relations(self):
        relation = self._create_relation(self.juan, self.type_sibling, self.pedro)
        self.assertEqual(relation.label, "brother of")

        self.type_sibling.name_male = "hermano de"

        self.assertEqual(relation.label, "hermano de")

    def test_two_mirrors_created_in_one_batch_are_refused(self):
        with self.assertRaises(ValidationError):
            self.relations.create(
                [
                    {
                        "partner_id": self.juan.id,
                        "type_id": self.type_spouse.id,
                        "other_partner_id": self.maria.id,
                    },
                    {
                        "partner_id": self.maria.id,
                        "type_id": self.type_spouse.id,
                        "other_partner_id": self.juan.id,
                    },
                ]
            )

    def test_a_batch_of_mirrors_is_checked_in_one_search(self):
        self._create_relation(self.juan, self.type_spouse, self.maria)
        self._create_relation(self.pedro, self.type_parent, self.lucia)
        relations = self.env["res.partner.relation"]
        original_search = type(relations).search
        calls = []

        def counting_search(records, *args, **kwargs):
            calls.append(records._name)
            return original_search(records, *args, **kwargs)

        self.patch(type(relations), "search", counting_search)
        batch = self.relations.create(
            [
                {
                    "partner_id": self.lucia.id,
                    "type_id": self.type_sibling.id,
                    "other_partner_id": self.pedro.id,
                },
                {
                    "partner_id": self.maria.id,
                    "type_id": self.type_sibling.id,
                    "other_partner_id": self.juan.id,
                },
                {
                    "partner_id": self.juan.id,
                    "type_id": self.type_compadre.id,
                    "other_partner_id": self.pedro.id,
                },
            ]
        )
        self.env.flush_all()

        self.assertEqual(len(batch), 3)
        self.assertEqual(calls, ["res.partner.relation"])
