from odoo.tests.common import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestCompanyCacheInvalidation(TransactionCase):
    """Regression coverage for RC-L2: res.company.cache_invalidation_fields()
    and the _accessible_branches() ormcache (res_company.py:511-516, 661-690).

    These tests assert CURRENT behaviour: writing a field listed in
    cache_invalidation_fields() (active/sequence) clears the registry cache so
    that the ormcache'd _accessible_branches() reflects the change, and that the
    accessible-branch list is ordered by the comodel _order ("sequence, name").
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Company = cls.env["res.company"]
        # Root company plus two direct branches. Branch sequences are chosen so
        # the initial child_ids order (sequence, name) is B1 then B2.
        cls.parent = Company.create({"name": "Audit Parent"})
        cls.branch1 = Company.create(
            {"name": "Audit Branch 1", "parent_id": cls.parent.id, "sequence": 10}
        )
        cls.branch2 = Company.create(
            {"name": "Audit Branch 2", "parent_id": cls.parent.id, "sequence": 20}
        )
        # A user whose accessible companies (env.companies) are exactly the three
        # companies above. With a dedicated, non-sudo user, env.companies falls
        # back to user._get_company_ids() so the __accessible_branches cache key
        # (tuple(env.companies.ids), self.id, env.uid) is fully controlled.
        cls.user = new_test_user(
            cls.env,
            login="audit_branch_user",
            company_id=cls.parent.id,
            company_ids=(cls.parent | cls.branch1 | cls.branch2).ids,
        )

    def test_cache_invalidation_fields_contents(self):
        """cache_invalidation_fields() returns exactly {'active', 'sequence'} today."""
        self.assertEqual(
            self.parent.cache_invalidation_fields(),
            {"active", "sequence"},
            "cache_invalidation_fields is self-documented as incomplete; assert "
            "the CURRENT set so the contract is pinned (RC-L2).",
        )

    def test_accessible_branches_returns_root_and_branches(self):
        """_accessible_branches() returns the root plus its accessible branches,
        ordered by the comodel _order ('sequence, name')."""
        parent = self.parent.with_user(self.user)
        accessible = parent._accessible_branches()
        # Root first (BFS level 0), then branches by sequence: B1 (10), B2 (20).
        self.assertEqual(
            accessible.ids,
            [self.parent.id, self.branch1.id, self.branch2.id],
            "Initial accessible branches must be root, branch1, branch2 (sequence order).",
        )

    def test_sequence_flip_reorders_accessible_branches(self):
        """Flipping a branch sequence reorders _accessible_branches() because
        'sequence' is in cache_invalidation_fields() (registry cache cleared)."""
        parent = self.parent.with_user(self.user)
        # Warm the ormcache with the initial ordering.
        self.assertEqual(
            parent._accessible_branches().ids,
            [self.parent.id, self.branch1.id, self.branch2.id],
        )
        # Move branch2 ahead of branch1. 'sequence' ∈ cache_invalidation_fields(),
        # so res.company.write() calls registry.clear_cache() (res_company.py:559-560).
        self.branch2.sequence = 1
        # The write clears the registry ormcache (sequence ∈ invalidation set);
        # also drop the transaction field cache so the cross-env `parent`
        # recordset re-reads child_ids in the new sequence order.
        self.env.flush_all()
        self.env.invalidate_all()
        reordered = parent._accessible_branches()
        self.assertEqual(
            reordered.ids,
            [self.parent.id, self.branch2.id, self.branch1.id],
            "After lowering branch2.sequence the cache must be invalidated and the "
            "BFS over child_ids (now branch2, branch1) reflected in the result.",
        )

    @mute_logger("odoo.models")
    def test_archived_branch_drops_from_accessible_branches(self):
        """Archiving a branch removes it from _accessible_branches(); 'active' is
        in cache_invalidation_fields() so the ormcache is invalidated."""
        parent = self.parent.with_user(self.user)
        # Warm the cache including both branches.
        self.assertIn(self.branch2.id, parent._accessible_branches().ids)
        # 'active' ∈ cache_invalidation_fields(); write() clears the registry cache.
        self.branch2.active = False
        accessible = parent._accessible_branches()
        self.assertNotIn(
            self.branch2.id,
            accessible.ids,
            "Archived branch must disappear from the (cache-invalidated) result.",
        )
        self.assertEqual(
            accessible.ids,
            [self.parent.id, self.branch1.id],
            "Only the root and the still-active branch remain.",
        )

    def test_accessible_branches_intersects_env_companies(self):
        """_accessible_branches() returns only branches present in env.companies;
        a user without a branch in company_ids does not see it (the intersection
        gate at res_company.py:677), even though child_ids still contains it."""
        limited_user = new_test_user(
            self.env,
            login="audit_limited_user",
            company_id=self.parent.id,
            company_ids=(self.parent | self.branch1).ids,
        )
        parent = self.parent.with_user(limited_user)
        accessible = parent._accessible_branches()
        self.assertEqual(
            accessible.ids,
            [self.parent.id, self.branch1.id],
            "branch2 is in the hierarchy but not in env.companies, so it is excluded.",
        )
        # The hierarchy itself is unchanged: child_ids still lists both branches.
        self.assertEqual(
            self.parent.child_ids.ids,
            [self.branch1.id, self.branch2.id],
        )
