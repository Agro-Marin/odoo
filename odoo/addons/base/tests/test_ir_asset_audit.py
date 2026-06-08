from odoo.tests.common import TransactionCase, tagged

from odoo.addons.base.models.ir_asset import AssetPaths


@tagged("post_install", "-at_install")
class TestAssetPathsReplace(TransactionCase):
    """IRASSET-L1: a REPLACE whose source path is already present in the bundle
    must reposition the source to the target slot, not silently drop it; and a
    source set that includes the target must keep the target (not delete it).

    These exercise the AssetPaths primitives (insert/move/remove) and the
    REPLACE branch logic of IrAsset._process_path directly -- no manifest/DB.
    """

    @staticmethod
    def _paths(asset_paths):
        return [a[0] for a in asset_paths.list]

    def _seed(self):
        ap = AssetPaths()
        ap.append(
            [
                ("/web/a.js", "/full/a.js", 1),
                ("/web/b.js", "/full/b.js", 1),
                ("/web/c.js", "/full/c.js", 1),
            ],
            "bundle1",
        )
        return ap

    def _replace(self, ap, target, source):
        """Mirror the fixed REPLACE branch of IrAsset._process_path."""
        target_index = ap.index(target, "bundle1")
        target_paths = [(target, "/full/x.js", 1)]
        target_in_source = any(p[0] == target for p in source)
        other = [p for p in source if p[0] != target]
        present = [p for p in other if p[0] in ap.memo]
        new = [p for p in other if p[0] not in ap.memo]
        ap.insert(new, "bundle1", target_index)
        if present:
            ap.move(present, "bundle1", target)
        if not target_in_source:
            ap.remove(target_paths, "bundle1")

    def test_replace_source_already_present(self):
        # replace c by a (a already in the bundle): a is repositioned to c's slot
        # and kept; before the fix insert() was a no-op and a was stranded / lost.
        ap = self._seed()
        self._replace(ap, "/web/c.js", [("/web/a.js", "/full/a.js", 1)])
        self.assertEqual(self._paths(ap), ["/web/b.js", "/web/a.js"])
        self.assertIn("/web/a.js", ap.memo)
        self.assertNotIn("/web/c.js", ap.memo)

    def test_replace_new_source_unchanged_behaviour(self):
        # replace c by a genuinely-new path d: d at c's slot, c removed (== today).
        ap = self._seed()
        self._replace(ap, "/web/c.js", [("/web/d.js", "/full/d.js", 1)])
        self.assertEqual(self._paths(ap), ["/web/a.js", "/web/b.js", "/web/d.js"])

    def test_replace_self_keeps_target(self):
        # replace c by c (or a glob whose matches include c): c must survive.
        ap = self._seed()
        self._replace(ap, "/web/c.js", [("/web/c.js", "/full/c.js", 1)])
        self.assertIn("/web/c.js", ap.memo)
        self.assertEqual(self._paths(ap), ["/web/a.js", "/web/b.js", "/web/c.js"])

    def test_move_primitive_repositions(self):
        ap = self._seed()
        ap.move([("/web/a.js", "/full/a.js", 1)], "bundle1", "/web/c.js")
        self.assertEqual(self._paths(ap), ["/web/b.js", "/web/a.js", "/web/c.js"])
        # before_path absent -> the moved block is appended at the end.
        ap.move([("/web/b.js", "/full/b.js", 1)], "bundle1", "/web/nope.js")
        self.assertEqual(self._paths(ap), ["/web/a.js", "/web/c.js", "/web/b.js"])


@tagged("post_install", "-at_install")
class TestDirectiveAbsentTarget(TransactionCase):
    """IRASSET-T1: pin the resolves-but-absent-in-bundle directive contract.

    The fork added warn+no-op for the *empty-resolution* target/path cases
    (covered in test_assetsbundle.py). This pins the *complementary* case: a
    target/path that resolves to a real file which is simply not part of THIS
    bundle. ``after`` / ``before`` / ``replace`` raise ValueError via
    ``AssetPaths.index`` (anchor must be present), and ``remove`` raises via
    ``AssetPaths.remove`` (the path to remove must be present). This is the
    upstream-faithful contract; pinning it makes a behaviour change a
    deliberate decision rather than a silent regression.
    """

    def _seed(self):
        ap = AssetPaths()
        ap.append(
            [
                ("/web/a.js", "/full/a.js", 1),
                ("/web/b.js", "/full/b.js", 1),
            ],
            "bundle1",
        )
        return ap

    def test_index_absent_target_raises_with_bundle(self):
        # The anchor used by after / before / replace resolves to a real path
        # that is simply not in this bundle: index() raises ValueError naming
        # the bundle (the directive cannot position relative to an absent anchor).
        ap = self._seed()
        with self.assertRaises(ValueError) as cm:
            ap.index("/web/absent.js", "bundle1")
        self.assertIn("bundle1", str(cm.exception))
        self.assertIn("/web/absent.js", str(cm.exception))

    def test_remove_resolvable_absent_path_raises_with_bundle(self):
        # remove of a path that resolves on disk but is not in this bundle
        # raises ValueError naming the bundle (upstream contract). Contrast with
        # the empty-resolution case (paths == []), which warns and no-ops.
        ap = self._seed()
        with self.assertRaises(ValueError) as cm:
            ap.remove([("/web/absent.js", "/full/absent.js", 1)], "bundle1")
        self.assertIn("bundle1", str(cm.exception))
        # The present paths are untouched by the failed remove.
        self.assertEqual([a[0] for a in ap.list], ["/web/a.js", "/web/b.js"])
