from odoo.tests import HttpCase, tagged

from .common import PartnerRelationCommon


@tagged("post_install", "-at_install")
class TestPartnerNetworkTour(PartnerRelationCommon, HttpCase):
    # A form sheet is capped at 1400px, so the width the full-page action gets
    # is only wrong above that. At the default 1366 the cap never binds and the
    # blank column it leaves cannot be seen.
    browser_size = "1920x1080"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.juan.name = "Juan Ramirez Solis"
        cls.household = cls.quick_ref("partner_relationship.relation_type_household")
        cls.business = cls.quick_ref(
            "partner_relationship.relation_type_businesspartner"
        )

        # One tie of every category, so the legend has all six entries and the
        # tour's nth-child(6) is an assertion rather than a coincidence, and so
        # that hiding one category is guaranteed to remove a node.
        cls._create_relation(cls.juan, cls.type_sibling, cls.maria)
        cls._create_relation(cls.juan, cls.type_spouse, cls.lucia)
        cls._create_relation(cls.juan, cls.type_compadre, cls.pedro)
        cls._create_relation(cls.juan, cls.household, cls.stranger)
        cls._create_relation(
            cls.juan, cls.business, cls._create_person("Rosa", "female")
        )
        cls._create_relation(
            cls.juan, cls.type_crop, cls._create_person("Diego", "male")
        )

    def test_the_network_draws_and_its_legend_filters(self):
        self.start_tour(
            "/odoo",
            "partner_network_tour",
            login="admin",
        )
