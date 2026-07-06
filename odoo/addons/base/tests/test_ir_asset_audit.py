from unittest.mock import patch

from odoo.modules import Manifest
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.base.models.ir_asset import AssetPaths


@tagged("post_install", "-at_install")
class TestReplaceDirective(TransactionCase):
    """IRASSET-L1 / IRASSET-C2: drive the REAL ``IrAsset._process_path`` REPLACE
    branch (not a re-implemented mirror) and pin its contract:

    * a source already present in the bundle is repositioned to the target
      slot, not silently dropped;
    * a source set that includes the target keeps the target;
    * the sources land at the target slot in **source order** (IRASSET-C2 --
      previously new-then-present, which reordered interleaved sources).
    """

    @staticmethod
    def _paths(ap):
        return [a.path for a in ap.list]

    def _seed(self, paths):
        ap = AssetPaths()
        ap.append([(p, "/full" + p, 1) for p in paths], "bundle1")
        return ap

    def _run_replace(self, ap, target_path, source_list):
        """Invoke the real _process_path REPLACE branch with resolution mocked."""
        IrAsset = self.env["ir.asset"]

        def fake_get_paths(_self, path_def, installed):
            if path_def == "TARGET":
                return [(target_path, "/full" + target_path, 1)]
            if path_def == "SOURCE":
                return list(source_list)
            return []

        with patch.object(type(IrAsset), "_get_paths", fake_get_paths):
            IrAsset._process_path(
                "bundle1", "replace", "TARGET", "SOURCE", ap, [], [], set(), 0
            )

    def test_replace_source_already_present(self):
        # replace /c by /a (already in the bundle): /a is repositioned to /c's
        # slot and kept; before the fix insert() was a no-op and /a was stranded.
        ap = self._seed(["/a", "/b", "/c"])
        self._run_replace(ap, "/c", [("/a", "/full/a", 1)])
        self.assertEqual(self._paths(ap), ["/b", "/a"])
        self.assertIn("/a", ap.memo)
        self.assertNotIn("/c", ap.memo)

    def test_replace_new_source(self):
        # replace /c by a genuinely-new path /d: /d at /c's slot, /c removed.
        ap = self._seed(["/a", "/b", "/c"])
        self._run_replace(ap, "/c", [("/d", "/full/d", 1)])
        self.assertEqual(self._paths(ap), ["/a", "/b", "/d"])

    def test_replace_self_keeps_target(self):
        # replace /c by /c (or a glob whose matches include /c): /c must survive.
        ap = self._seed(["/a", "/b", "/c"])
        self._run_replace(ap, "/c", [("/c", "/full/c", 1)])
        self.assertEqual(self._paths(ap), ["/a", "/b", "/c"])
        self.assertIn("/c", ap.memo)

    def test_replace_empty_source_removes_target(self):
        # documented "delete the target" idiom: empty source removes the target.
        ap = self._seed(["/a", "/b", "/c"])
        self._run_replace(ap, "/b", [])
        self.assertEqual(self._paths(ap), ["/a", "/c"])
        self.assertNotIn("/b", ap.memo)

    def test_replace_preserves_source_order(self):
        # IRASSET-C2: sources interleave already-present (/a, /b) and new
        # (/x, /y).  The result must follow SOURCE order [/a, /x, /b, /y], not
        # the old new-then-present order [/x, /y, /a, /b].
        ap = self._seed(["/a", "/b", "/T"])
        source = [
            ("/a", "/full/a", 1),
            ("/x", "/full/x", 1),
            ("/b", "/full/b", 1),
            ("/y", "/full/y", 1),
        ]
        self._run_replace(ap, "/T", source)
        self.assertEqual(self._paths(ap), ["/a", "/x", "/b", "/y"])
        self.assertNotIn("/T", ap.memo)

    def test_replace_glob_including_target_keeps_target_and_orders_new(self):
        # target glob matches /T; source glob matches [/n1, /T, /n2].  /T stays;
        # the new sources land before it in source order.
        ap = self._seed(["/T", "/c"])
        source = [
            ("/n1", "/full/n1", 1),
            ("/T", "/full/T", 1),
            ("/n2", "/full/n2", 1),
        ]
        self._run_replace(ap, "/T", source)
        self.assertEqual(self._paths(ap), ["/n1", "/n2", "/T", "/c"])


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
        self.assertEqual([a.path for a in ap.list], ["/web/a.js", "/web/b.js"])

    def test_replace_absent_target_raises_via_process_path(self):
        # End-to-end through the REAL _process_path: a REPLACE whose target
        # resolves to a real file absent from the bundle raises.
        IrAsset = self.env["ir.asset"]
        ap = self._seed()

        def fake_get_paths(_self, path_def, installed):
            return [(path_def, "/full" + path_def, 1)]

        with patch.object(type(IrAsset), "_get_paths", fake_get_paths):
            with self.assertRaises(ValueError) as cm:
                IrAsset._process_path(
                    "bundle1", "replace", "/web/absent.js", "/web/x.js",
                    ap, [], [], set(), 0,
                )
        self.assertIn("/web/absent.js", str(cm.exception))
        self.assertIn("bundle1", str(cm.exception))


@tagged("post_install", "-at_install")
class TestGetPathsEscapeWarning(TransactionCase):
    """IRASSET-C4: a non-wildcard path naming an installed addon but resolving
    *outside* that addon's ``static/`` directory silently degrades to an
    attachment URL. That escape used to be the one resolution outcome with no
    log trace; pin that it now warns -- while a path that stays inside
    ``static/`` (merely missing on disk) must NOT warn.
    """

    def test_escape_outside_static_warns(self):
        IrAsset = self.env["ir.asset"]
        installed = IrAsset._get_installed_addons_list()
        escaping = "/base/static/../../../../etc/passwd"
        with self.assertLogs(
            "odoo.addons.base.models.ir_asset", level="WARNING"
        ) as cm:
            result = IrAsset._get_paths(escaping, installed)
        joined = "\n".join(cm.output)
        self.assertIn("resolves outside the static/", joined)
        # It still degrades to a (doomed) attachment tuple -- unchanged behaviour.
        self.assertEqual(result, [(escaping, None, None)])

    def test_missing_inside_static_does_not_warn(self):
        IrAsset = self.env["ir.asset"]
        installed = IrAsset._get_installed_addons_list()
        # Inside base/static, just not present on disk: attachment fallback,
        # but this is not an escape, so no escape warning is emitted.
        inside = "/base/static/src/scss/__does_not_exist__.scss"
        with self.assertNoLogs(
            "odoo.addons.base.models.ir_asset", level="WARNING"
        ):
            result = IrAsset._get_paths(inside, installed)
        self.assertEqual(result, [(inside, None, None)])


@tagged("post_install", "-at_install")
class TestProcessCommandMalformed(TransactionCase):
    """IRASSET-A2: a malformed manifest asset command must raise a ValueError
    whose message names the offending command.

    The parser's whole purpose in catching is to attach ``command`` to the
    error. Previously it only caught ``(ValueError, IndexError)`` and used
    ``add_note`` -- so a non-subscriptable command (int, None) escaped as a raw
    ``TypeError`` and a dict escaped as ``KeyError``, both WITHOUT the command
    in ``str(exc)``. Pin that every malformed shape surfaces the command in the
    exception message itself.
    """

    def test_int_command_raises_valueerror_naming_command(self):
        with self.assertRaises(ValueError) as cm:
            self.env["ir.asset"]._process_command(123)
        self.assertIn("123", str(cm.exception))

    def test_dict_command_raises_valueerror_naming_command(self):
        with self.assertRaises(ValueError) as cm:
            self.env["ir.asset"]._process_command({"path": "x"})
        self.assertIn("path", str(cm.exception))

    def test_wrong_arity_raises_valueerror_naming_command(self):
        # command[0] is a valid directive but the tuple has the wrong length:
        # the command must still appear in str(exc), not only in __notes__.
        with self.assertRaises(ValueError) as cm:
            self.env["ir.asset"]._process_command(["after", "only_two"])
        self.assertIn("only_two", str(cm.exception))


@tagged("post_install", "-at_install")
class TestReorderPresentSourceWarns(TransactionCase):
    """IRASSET-A1: AFTER/BEFORE with a source already present in the bundle is a
    silent no-op -- ``insert`` dedups it, so it is NOT repositioned (unlike
    REPLACE, which pulls present sources out and re-inserts them at the target
    slot). Pin that this asymmetry now emits a WARNING so an ineffective
    reorder directive is visible instead of vanishing.
    """

    def _run(self, directive, target, source_path):
        IrAsset = self.env["ir.asset"]
        ap = AssetPaths()
        ap.append(
            [("/a", "/f/a", 1), ("/b", "/f/b", 1), ("/c", "/f/c", 1)], "bundle1"
        )

        def fake_get_paths(_self, path_def, installed):
            resolved = target if path_def == target else source_path
            return [(resolved, "/f" + resolved, 1)]

        with patch.object(type(IrAsset), "_get_paths", fake_get_paths):
            with self.assertLogs(
                "odoo.addons.base.models.ir_asset", level="WARNING"
            ) as cm:
                IrAsset._process_path(
                    "bundle1", directive, target, source_path,
                    ap, [], [], set(), 0,
                )
        return [a.path for a in ap.list], " ".join(cm.output)

    def test_after_present_source_warns_and_is_noop(self):
        paths, log = self._run("after", "/a", "/c")  # /c already present
        self.assertEqual(paths, ["/a", "/b", "/c"])  # unchanged
        self.assertIn("already present", log)
        self.assertIn("bundle1", log)
        self.assertIn("/c", log)

    def test_before_present_source_warns(self):
        _paths, log = self._run("before", "/b", "/c")
        self.assertIn("already present", log)
        self.assertIn("/c", log)


@tagged("post_install", "-at_install")
class TestRemovePartialAbsentWarns(TransactionCase):
    """IRASSET-A3: ``AssetPaths.remove`` of a set that mixes present and absent
    paths removes the present ones but used to silently ignore the absent ones
    -- inconsistent with the all-absent case (which raises) and the
    empty-resolution case (which warns). Pin that the ignored, stale subset now
    emits a WARNING naming it, while an all-present remove stays silent.
    """

    def _seed(self):
        ap = AssetPaths()
        ap.append([("/a", "/f/a", 1), ("/b", "/f/b", 1)], "bundle1")
        return ap

    def test_partial_absent_remove_warns_and_removes_present(self):
        ap = self._seed()
        with self.assertLogs(
            "odoo.addons.base.models.ir_asset", level="WARNING"
        ) as cm:
            ap.remove([("/b", "/f/b", 1), ("/zzz", "/f/zzz", 1)], "bundle1")
        self.assertEqual([a.path for a in ap.list], ["/a"])
        joined = " ".join(cm.output)
        self.assertIn("/zzz", joined)
        self.assertIn("bundle1", joined)

    def test_all_present_remove_is_silent(self):
        ap = self._seed()
        with self.assertNoLogs(
            "odoo.addons.base.models.ir_asset", level="WARNING"
        ):
            ap.remove([("/b", "/f/b", 1)], "bundle1")
        self.assertEqual([a.path for a in ap.list], ["/a"])


@tagged("post_install", "-at_install")
class TestGlobRemoveIsSetSubtraction(TransactionCase):
    """Task 23534: a wildcarded ``remove`` resolves against files on DISK
    while the bundle usually holds only a subset of them (e.g. mail removes
    ``discuss/**/*`` from ``web.assets_backend`` before re-adding the allowed
    subsets, and ``**/*.dark.scss`` globs match files only ever added to the
    dark bundles). Absent disk matches are expected set subtraction, not
    staleness: through ``_process_path`` a glob remove stays silent on partial
    or full absence, while a literal remove keeps the strict IRASSET-A3
    contract (warn on partial, raise on all-absent).
    """

    def _seed(self):
        ap = AssetPaths()
        ap.append(
            [("/web/a.js", "/f/a.js", 1), ("/web/b.js", "/f/b.js", 1)],
            "bundle1",
        )
        return ap

    def _run_remove(self, path_def, resolved, ap):
        IrAsset = self.env["ir.asset"]

        def fake_get_paths(_self, _path_def, installed):
            return resolved

        with patch.object(type(IrAsset), "_get_paths", fake_get_paths):
            IrAsset._process_path(
                "bundle1", "remove", None, path_def, ap, [], [], set(), 0,
            )

    def test_glob_remove_partial_absent_is_silent(self):
        ap = self._seed()
        with self.assertNoLogs(
            "odoo.addons.base.models.ir_asset", level="WARNING"
        ):
            self._run_remove(
                "/web/**/*.js",
                [("/web/b.js", "/f/b.js", 1), ("/web/zzz.js", "/f/zzz.js", 1)],
                ap,
            )
        self.assertEqual([a.path for a in ap.list], ["/web/a.js"])

    def test_glob_remove_none_present_is_silent_noop(self):
        ap = self._seed()
        with self.assertNoLogs(
            "odoo.addons.base.models.ir_asset", level="WARNING"
        ):
            self._run_remove(
                "/web/**/*.dark.scss",
                [("/web/x.dark.scss", "/f/x.dark.scss", 1)],
                ap,
            )
        self.assertEqual(
            [a.path for a in ap.list], ["/web/a.js", "/web/b.js"]
        )

    def test_literal_remove_absent_still_raises(self):
        ap = self._seed()
        with self.assertRaises(ValueError):
            self._run_remove(
                "/web/absent.js",
                [("/web/absent.js", "/f/absent.js", 1)],
                ap,
            )
        self.assertEqual(
            [a.path for a in ap.list], ["/web/a.js", "/web/b.js"]
        )


@tagged("post_install", "-at_install")
class TestTopologicalSort(TransactionCase):
    """IRASSET-D1: ``_topological_sort`` governs asset load order but had no
    direct unit test. Pin its core contract with synthetic manifests: every
    dependency precedes its dependents, missing ``depends`` falls back to
    ``base``, and the full input set is returned.
    """

    def _sort(self, manifests, addons):
        IrAsset = self.env["ir.asset"]
        # ``_topological_sort`` is @ormcache'd on the addons tuple; run inside a
        # fresh cache so synthetic runs don't collide with real ones.
        IrAsset.env.registry.clear_cache()
        with patch.object(Manifest, "for_addon", lambda name, **kw: manifests.get(name)):
            return IrAsset._topological_sort(tuple(addons))

    def test_dependency_precedes_dependents(self):
        manifests = {
            "base": {"depends": []},
            "app_mod": {"depends": ["base"], "application": True},
            "mid_mod": {"depends": ["app_mod"]},
            "leaf_mod": {"depends": ["mid_mod", "base"]},
        }
        order = self._sort(manifests, manifests)
        self.assertEqual(set(order), set(manifests), "all inputs returned")
        pos = {name: order.index(name) for name in manifests}
        self.assertLess(pos["base"], pos["app_mod"])
        self.assertLess(pos["app_mod"], pos["mid_mod"])
        self.assertLess(pos["mid_mod"], pos["leaf_mod"])
        self.assertLess(pos["base"], pos["leaf_mod"])

    def test_missing_depends_falls_back_to_base(self):
        # A manifest with no ``depends`` key is treated as depending on base, so
        # base must come first (the ``manif.get("depends") or ["base"]`` rule).
        manifests = {"base": {"depends": []}, "orphan": {}}
        order = self._sort(manifests, ["orphan", "base"])
        self.assertLess(order.index("base"), order.index("orphan"))


@tagged("post_install", "-at_install")
class TestAssetPathsCacheCanonical(TransactionCase):
    """IRASSET-P1: ``_get_asset_paths`` sorts the active-addons set before
    building the ``_topological_sort`` @ormcache key, so the key is canonical
    regardless of the process-dependent iteration order of the addon set (set
    hash randomization). Pin that the tuple handed to ``_topological_sort`` is
    sorted, preventing cross-worker cache fragmentation.
    """

    def test_addons_are_sorted_into_topological_sort_key(self):
        IrAsset = self.env["ir.asset"]
        captured = []

        def spy_topo(_self, addons_tuple):
            captured.append(addons_tuple)
            return list(addons_tuple)

        cls = type(IrAsset)
        with patch.object(
            cls, "_get_active_addons_list",
            lambda _self, **k: ["web", "base", "mail"],
        ), patch.object(
            cls, "_get_related_assets", lambda _self, domain, **k: IrAsset.browse()
        ), patch.object(cls, "_topological_sort", spy_topo):
            IrAsset._get_asset_paths("irasset_p1_probe.bundle", {})

        self.assertTrue(captured, "_topological_sort was invoked")
        self.assertEqual(captured[0], ("base", "mail", "web"))
