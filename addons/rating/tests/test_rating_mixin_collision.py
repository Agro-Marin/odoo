"""The two rating mixins share four field names and mean different things by them."""

from odoo.tests import TransactionCase, tagged

SHARED_FIELD_NAMES = (
    "rating_ids",
    "rating_count",
    "rating_avg",
    "rating_percentage_satisfaction",
)


@tagged("post_install", "-at_install")
class TestRatingMixinCollision(TransactionCase):
    def test_the_two_mixins_still_disagree_about_four_field_names(self):
        # Not a defect to fix here, but the premise every other test in this
        # file rests on. mixin.rating scopes to ratings ON the record
        # (res_model/res_id); mixin.rating.parent scopes to ratings on its
        # CHILDREN (parent_res_model/parent_res_id).
        rated = self.env["mixin.rating"]._fields
        parent = self.env["mixin.rating.parent"]._fields
        for name in SHARED_FIELD_NAMES:
            with self.subTest(field=name):
                self.assertIn(name, rated)
                self.assertIn(name, parent)

    def test_rating_avg_percentage_is_not_computed_beside_rating_avg(self):
        # The corruption this guards: a model inheriting BOTH mixins resolves
        # rating_avg to mixin.rating's compute, while rating_avg_percentage
        # keeps the parent's. If one method assigned both, reading the
        # percentage would silently overwrite rating_avg with the other
        # mixin's answer -- reproduced as 5.0 becoming 1.0 on the same record
        # in one transaction, with no write between the two reads.
        parent = self.env["mixin.rating.parent"]._fields
        self.assertNotEqual(
            parent["rating_avg_percentage"].compute,
            parent["rating_avg"].compute,
            "rating_avg_percentage must derive from rating_avg, not be assigned "
            "alongside it, or a model carrying both rating mixins corrupts "
            "rating_avg on read",
        )
        # Resolved through the registry: Field carries no public `depends`.
        consumer = self.env["project.project"]
        depends = self.env.registry.field_depends[
            consumer._fields["rating_avg_percentage"]
        ]
        self.assertIn("rating_avg", tuple(depends))

    def test_the_percentage_still_tracks_the_average_it_derives_from(self):
        project = self.env["project.project"].create({"name": "Rating parent"})
        self.assertEqual(project.rating_avg_percentage, project.rating_avg / 5)
