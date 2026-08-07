from odoo.tests.common import TransactionCase


class TestTagTag(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Tag = cls.env["tag.tag"]
        cls.root = Tag.create({"name": "Rootag"})
        cls.mid = Tag.create({"name": "Midtag", "parent_id": cls.root.id})
        cls.leaf = Tag.create({"name": "Leaftag", "parent_id": cls.mid.id})
        cls.other = Tag.create({"name": "Loosetag"})

    def test_display_name_is_full_ancestor_path(self):
        self.assertEqual(self.root.display_name, "Rootag")
        self.assertEqual(self.mid.display_name, "Rootag / Midtag")
        self.assertEqual(self.leaf.display_name, "Rootag / Midtag / Leaftag")
        self.assertEqual(self.other.display_name, "Loosetag")

    def test_display_name_batched_recompute(self):
        tags = self.root + self.mid + self.leaf + self.other
        tags.invalidate_recordset(["display_name"])
        self.assertEqual(
            tags.mapped("display_name"),
            ["Rootag", "Rootag / Midtag", "Rootag / Midtag / Leaftag", "Loosetag"],
        )

    def test_display_name_follows_ancestor_rename(self):
        self.root.name = "Renamedtag"
        self.assertEqual(self.leaf.display_name, "Renamedtag / Midtag / Leaftag")

    def test_display_name_includes_archived_ancestor(self):
        self.root.active = False
        (self.mid + self.leaf).invalidate_recordset(["display_name"])
        self.assertEqual(self.leaf.display_name, "Rootag / Midtag / Leaftag")

    def test_display_name_newid_cycle_terminates(self):
        Tag = self.env["tag.tag"]
        first = Tag.new({"name": "Firstag"})
        second = Tag.new({"name": "Secondtag"})
        first.parent_id = second
        second.parent_id = first
        self.assertEqual(first.display_name, "Secondtag / Firstag")
        self.assertEqual(second.display_name, "Firstag / Secondtag")

    def test_display_name_newid_without_parent(self):
        self.assertEqual(self.env["tag.tag"].new({"name": "Solo"}).display_name, "Solo")

    def test_display_name_resolved_in_constant_queries(self):
        Tag = self.env["tag.tag"]
        parent = self.env["tag.tag"]
        deep_ids = []
        for level in range(10):
            parent = Tag.create({"name": f"Deep{level}", "parent_id": parent.id})
            deep_ids.append(parent.id)
        self.env.flush_all()
        self.env.invalidate_all()
        leaf = Tag.browse(deep_ids[-1])
        self.assertEqual(
            leaf.display_name,
            " / ".join(f"Deep{level}" for level in range(10)),
        )

    def test_search_display_name_like_expands_to_subtree(self):
        found = self.env["tag.tag"].search([("display_name", "like", "Midtag")])
        self.assertEqual(set(found.ids), {self.mid.id, self.leaf.id})

        found = self.env["tag.tag"].search([("display_name", "like", "Rootag")])
        self.assertEqual(set(found.ids), {self.root.id, self.mid.id, self.leaf.id})

    def test_search_display_name_like_archived_root(self):
        self.root.active = False
        found = self.env["tag.tag"].search([("display_name", "like", "Rootag")])
        self.assertFalse(found)
        found = (
            self.env["tag.tag"]
            .with_context(active_test=False)
            .search([("display_name", "like", "Rootag")])
        )
        self.assertEqual(set(found.ids), {self.root.id, self.mid.id, self.leaf.id})

    def test_search_display_name_not_like_excludes_subtree(self):
        scope = (self.root + self.mid + self.leaf + self.other).ids
        found = self.env["tag.tag"].search(
            [("display_name", "not like", "Midtag"), ("id", "in", scope)]
        )
        self.assertEqual(set(found.ids), {self.root.id, self.other.id})

    def test_name_search_matches_subtree(self):
        found_ids = [rid for rid, _name in self.env["tag.tag"].name_search("Midtag")]
        self.assertIn(self.mid.id, found_ids)
        self.assertIn(self.leaf.id, found_ids)
        self.assertNotIn(self.root.id, found_ids)
        self.assertNotIn(self.other.id, found_ids)
