from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestRemovalStrategyLineage(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Removal = cls.env["product.removal"]
        cls.lifo = Removal.search([("method", "=", "lifo")], limit=1)
        cls.closest = Removal.search([("method", "=", "closest")], limit=1)
        cls.Quant = cls.env["stock.quant"]
        cls.Location = cls.env["stock.location"]
        cls.product = cls.env["product.product"].create(
            {"name": "Lineage product", "is_storable": True}
        )
        parent = cls.env.ref("stock.stock_location_stock")
        cls.chain = cls.Location
        for index in range(4):
            parent = cls.Location.create(
                {"name": "lineage-%s" % index, "location_id": parent.id}
            )
            cls.chain |= parent
        cls.chain[0].removal_strategy_id = cls.closest
        cls.chain[2].removal_strategy_id = cls.lifo
        cls.deep = cls.chain[-1]

    def strategy(self, location):
        return self.Quant._get_removal_strategy(self.product, location)

    def test_a_stored_location_takes_its_nearest_ancestor_strategy(self):
        self.env.invalidate_all()
        self.assertEqual(self.strategy(self.deep), "lifo")
        self.assertEqual(self.strategy(self.chain[1]), "closest")
        self.assertEqual(self.strategy(self.chain[0].location_id), "fifo")

    def test_ancestor_depth_does_not_add_queries(self):
        self.chain[2].removal_strategy_id = False

        def statements(location):
            self.env.flush_all()
            self.env.invalidate_all()
            self.product.categ_id.removal_strategy_id.method
            before = self.env.cr.sql_statement_count
            self.assertEqual(self.strategy(location), "closest")
            return self.env.cr.sql_statement_count - before

        self.assertEqual(statements(self.chain[1]), statements(self.deep))

    def test_a_new_location_walks_up_to_its_stored_parent(self):
        draft = self.Location.new({"name": "draft", "location_id": self.deep.id})
        self.assertEqual(self.strategy(draft), "lifo")
        draft.removal_strategy_id = self.closest
        self.assertEqual(self.strategy(draft), "closest")

    def test_a_chain_of_new_locations_is_walked_to_the_first_strategy(self):
        draft_parent = self.Location.new(
            {"name": "draft parent", "location_id": self.chain[0].id}
        )
        draft_child = self.Location.new(
            {"name": "draft child", "location_id": draft_parent.id}
        )
        self.assertEqual(self.strategy(draft_child), "closest")
        draft_parent.removal_strategy_id = self.lifo
        self.assertEqual(self.strategy(draft_child), "lifo")

    def test_an_edited_location_uses_its_pending_strategy_not_the_stored_one(self):
        edited = self.Location.new(
            {"removal_strategy_id": self.closest.id}, origin=self.chain[2]
        )
        self.assertEqual(self.strategy(edited), "closest")
