from odoo.tests.common import TransactionCase


class TestTagTag(TransactionCase):
    """TAG-T1: cover the fork-specific tag.mixin logic through tag.tag.

    Exercises the frontier-walk batched ``_compute_display_name`` (full
    ancestor path) and the hierarchical ``_search_display_name`` rewrite
    (positive ``like`` expands to the matched subtree via ``child_of``;
    negative ``like`` is NotImplemented and handled by the ORM's
    positive-operator fallback).
    """

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

    def test_display_name_batched_frontier_walk(self):
        # the compute walks all records' ancestor chains level by level in
        # one batch; recomputing the whole set at once must give the same
        # result as record-by-record access
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
        # archiving a parent hides it from searches but must not truncate the
        # ancestor path of its active descendants
        self.root.active = False
        (self.mid + self.leaf).invalidate_recordset(["display_name"])
        self.assertEqual(self.leaf.display_name, "Rootag / Midtag / Leaftag")

    def test_search_display_name_like_expands_to_subtree(self):
        # the hierarchical rewrite turns a positive match into child_of: the
        # matched tag and its whole subtree are returned
        found = self.env["tag.tag"].search([("display_name", "like", "Midtag")])
        self.assertEqual(set(found.ids), {self.mid.id, self.leaf.id})

        found = self.env["tag.tag"].search([("display_name", "like", "Rootag")])
        self.assertEqual(set(found.ids), {self.root.id, self.mid.id, self.leaf.id})

    def test_search_display_name_like_archived_root(self):
        # the subtree expansion resolves the matched tags with the ambient
        # active_test: an archived root no longer anchors the match, so
        # neither it nor its (active) subtree is returned by name
        self.root.active = False
        found = self.env["tag.tag"].search([("display_name", "like", "Rootag")])
        self.assertFalse(found)
        # with active_test disabled, the whole subtree is found again
        found = (
            self.env["tag.tag"]
            .with_context(active_test=False)
            .search([("display_name", "like", "Rootag")])
        )
        self.assertEqual(set(found.ids), {self.root.id, self.mid.id, self.leaf.id})

    def test_search_display_name_not_like_excludes_subtree(self):
        # 'not like' returns NotImplemented from _search_display_name; the
        # ORM falls back to negating the positive rewrite, so the matched
        # tag AND its descendants are excluded
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
