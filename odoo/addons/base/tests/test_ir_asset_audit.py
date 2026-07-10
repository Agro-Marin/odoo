from unittest.mock import patch

from odoo.modules import Manifest
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.base.models.ir_asset import AssetPaths


@tagged("post_install", "-at_install")
class TestReplaceDirective(TransactionCase):
    """IRASSET-L1 / IRASSET-C2: pin the real ``IrAsset._process_path`` REPLACE
    branch. A present source is repositioned to the target slot (not dropped), a
    source set including the target keeps it, and sources land in source order
    (IRASSET-C2 — the old new-then-present order reordered interleaved sources).
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
        # replace /c by /a (already present): /a moves to /c's slot; the old
        # insert() no-op stranded /a.
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
        # IRASSET-C2: interleaved present (/a, /b) and new (/x, /y) sources must
        # follow SOURCE order [/a, /x, /b, /y], not the old [/x, /y, /a, /b].
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
    """IRASSET-T1: pin the resolves-but-absent-in-bundle contract. A target/path
    resolving to a real file absent from THIS bundle makes after/before/replace
    raise via ``AssetPaths.index`` and remove raise via ``AssetPaths.remove``.
    The empty-resolution case (warn+no-op) lives in test_assetsbundle.py.
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
        # Anchor resolves to a real path absent from this bundle: index() raises
        # ValueError naming the bundle (can't position relative to an absent anchor).
        ap = self._seed()
        with self.assertRaises(ValueError) as cm:
            ap.index("/web/absent.js", "bundle1")
        self.assertIn("bundle1", str(cm.exception))
        self.assertIn("/web/absent.js", str(cm.exception))

    def test_remove_resolvable_absent_path_raises_with_bundle(self):
        # remove of a path resolving on disk but absent from this bundle raises
        # ValueError naming the bundle; the empty-resolution case warns and no-ops.
        ap = self._seed()
        with self.assertRaises(ValueError) as cm:
            ap.remove([("/web/absent.js", "/full/absent.js", 1)], "bundle1")
        self.assertIn("bundle1", str(cm.exception))
        # The present paths are untouched by the failed remove.
        self.assertEqual([a.path for a in ap.list], ["/web/a.js", "/web/b.js"])

    def test_replace_absent_target_raises_via_process_path(self):
        # End-to-end through the real _process_path: a REPLACE whose target
        # resolves to a real file absent from the bundle raises.
        IrAsset = self.env["ir.asset"]
        ap = self._seed()

        def fake_get_paths(_self, path_def, installed):
            return [(path_def, "/full" + path_def, 1)]

        with patch.object(type(IrAsset), "_get_paths", fake_get_paths):
            with self.assertRaises(ValueError) as cm:
                IrAsset._process_path(
                    "bundle1",
                    "replace",
                    "/web/absent.js",
                    "/web/x.js",
                    ap,
                    [],
                    [],
                    set(),
                    0,
                )
        self.assertIn("/web/absent.js", str(cm.exception))
        self.assertIn("bundle1", str(cm.exception))


@tagged("post_install", "-at_install")
class TestGetPathsEscapeWarning(TransactionCase):
    """IRASSET-C4 / IRASSET-C5: the two non-wildcard resolution outcomes that
    silently degraded to an attachment URL must each leave a distinct trace.
    C4: a path naming an installed addon but resolving outside its ``static/``
    (escape). C5: a literal path inside ``static/`` matching no file (typo).
    Both keep the attachment-URL degradation (attachment rows may legitimately
    shadow a since-removed static file).
    """

    def test_escape_outside_static_warns(self):
        IrAsset = self.env["ir.asset"]
        installed = IrAsset._get_installed_addons_list()
        escaping = "/base/static/../../../../etc/passwd"
        with self.assertLogs("odoo.addons.base.models.ir_asset", level="WARNING") as cm:
            result = IrAsset._get_paths(escaping, installed)
        joined = "\n".join(cm.output)
        self.assertIn("resolves outside the static/", joined)
        # Still degrades to a (doomed) attachment tuple -- unchanged behaviour.
        self.assertEqual(result, [(escaping, None, None)])

    def test_missing_literal_inside_static_warns_typo(self):
        IrAsset = self.env["ir.asset"]
        installed = IrAsset._get_installed_addons_list()
        # Inside base/static but absent on disk: attachment fallback with the C5
        # typo warning (not the C4 escape warning).
        inside = "/base/static/src/scss/__does_not_exist__.scss"
        with self.assertLogs("odoo.addons.base.models.ir_asset", level="WARNING") as cm:
            result = IrAsset._get_paths(inside, installed)
        joined = "\n".join(cm.output)
        self.assertIn("matches no bundleable file in the static/", joined)
        self.assertNotIn("resolves outside the static/", joined)
        self.assertEqual(result, [(inside, None, None)])

    def test_existing_literal_inside_static_does_not_warn(self):
        IrAsset = self.env["ir.asset"]
        installed = IrAsset._get_installed_addons_list()
        # A literal path that DOES resolve must stay warning-free.
        inside = "/base/static/src/scss/res_users.scss"
        with self.assertNoLogs("odoo.addons.base.models.ir_asset", level="WARNING"):
            result = IrAsset._get_paths(inside, installed)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], inside)
        self.assertIsNotNone(result[0][1])


@tagged("post_install", "-at_install")
class TestProcessCommandMalformed(TransactionCase):
    """IRASSET-A2: a malformed manifest asset command must raise ValueError whose
    message names the offending command. The parser previously caught only
    ``(ValueError, IndexError)`` via ``add_note``, so a non-subscriptable command
    (int/None) escaped as TypeError and a dict as KeyError, both without the
    command in ``str(exc)``. Pin that every malformed shape surfaces it.
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
        # Valid directive but wrong arity: the command must still appear in
        # str(exc), not only in __notes__.
        with self.assertRaises(ValueError) as cm:
            self.env["ir.asset"]._process_command(["after", "only_two"])
        self.assertIn("only_two", str(cm.exception))


@tagged("post_install", "-at_install")
class TestReorderPresentSourceWarns(TransactionCase):
    """IRASSET-A1: AFTER/BEFORE with an already-present source is a silent no-op
    (``insert`` dedups it, so it is not repositioned — unlike REPLACE, which
    pulls present sources out and re-inserts them at the target slot). Pin that
    this asymmetry now emits a WARNING so the ineffective directive is visible.
    """

    def _run(self, directive, target, source_path):
        IrAsset = self.env["ir.asset"]
        ap = AssetPaths()
        ap.append([("/a", "/f/a", 1), ("/b", "/f/b", 1), ("/c", "/f/c", 1)], "bundle1")

        def fake_get_paths(_self, path_def, installed):
            resolved = target if path_def == target else source_path
            return [(resolved, "/f" + resolved, 1)]

        with patch.object(type(IrAsset), "_get_paths", fake_get_paths):
            with self.assertLogs(
                "odoo.addons.base.models.ir_asset", level="WARNING"
            ) as cm:
                IrAsset._process_path(
                    "bundle1",
                    directive,
                    target,
                    source_path,
                    ap,
                    [],
                    [],
                    set(),
                    0,
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
    """IRASSET-A3: ``AssetPaths.remove`` of a mix of present and absent paths
    removes the present ones but used to silently ignore the absent ones —
    inconsistent with the all-absent (raises) and empty-resolution (warns) cases.
    Pin that the stale subset now emits a WARNING while all-present stays silent.
    """

    def _seed(self):
        ap = AssetPaths()
        ap.append([("/a", "/f/a", 1), ("/b", "/f/b", 1)], "bundle1")
        return ap

    def test_partial_absent_remove_warns_and_removes_present(self):
        ap = self._seed()
        with self.assertLogs("odoo.addons.base.models.ir_asset", level="WARNING") as cm:
            ap.remove([("/b", "/f/b", 1), ("/zzz", "/f/zzz", 1)], "bundle1")
        self.assertEqual([a.path for a in ap.list], ["/a"])
        joined = " ".join(cm.output)
        self.assertIn("/zzz", joined)
        self.assertIn("bundle1", joined)

    def test_all_present_remove_is_silent(self):
        ap = self._seed()
        with self.assertNoLogs("odoo.addons.base.models.ir_asset", level="WARNING"):
            ap.remove([("/b", "/f/b", 1)], "bundle1")
        self.assertEqual([a.path for a in ap.list], ["/a"])


@tagged("post_install", "-at_install")
class TestGlobRemoveIsSetSubtraction(TransactionCase):
    """Task 23534: a wildcarded ``remove`` resolves against files on disk while
    the bundle usually holds only a subset of them (e.g. mail removes
    ``discuss/**/*`` before re-adding allowed subsets; ``**/*.dark.scss`` matches
    files only in the dark bundles). Absent disk matches are expected set
    subtraction, so a glob remove stays silent on partial/full absence, while a
    literal remove keeps the IRASSET-A3 contract (warn on partial, raise on all).
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
                "bundle1",
                "remove",
                None,
                path_def,
                ap,
                [],
                [],
                set(),
                0,
            )

    def test_glob_remove_partial_absent_is_silent(self):
        ap = self._seed()
        with self.assertNoLogs("odoo.addons.base.models.ir_asset", level="WARNING"):
            self._run_remove(
                "/web/**/*.js",
                [("/web/b.js", "/f/b.js", 1), ("/web/zzz.js", "/f/zzz.js", 1)],
                ap,
            )
        self.assertEqual([a.path for a in ap.list], ["/web/a.js"])

    def test_glob_remove_none_present_is_silent_noop(self):
        ap = self._seed()
        with self.assertNoLogs("odoo.addons.base.models.ir_asset", level="WARNING"):
            self._run_remove(
                "/web/**/*.dark.scss",
                [("/web/x.dark.scss", "/f/x.dark.scss", 1)],
                ap,
            )
        self.assertEqual([a.path for a in ap.list], ["/web/a.js", "/web/b.js"])

    def test_literal_remove_absent_still_raises(self):
        ap = self._seed()
        with self.assertRaises(ValueError):
            self._run_remove(
                "/web/absent.js",
                [("/web/absent.js", "/f/absent.js", 1)],
                ap,
            )
        self.assertEqual([a.path for a in ap.list], ["/web/a.js", "/web/b.js"])


@tagged("post_install", "-at_install")
class TestTopologicalSort(TransactionCase):
    """IRASSET-D1: pin ``_topological_sort`` (asset load order) with synthetic
    manifests: every dependency precedes its dependents, missing ``depends``
    falls back to ``base``, and the full input set is returned.
    """

    def _sort(self, manifests, addons):
        IrAsset = self.env["ir.asset"]
        # @ormcache'd on the addons tuple; clear so synthetic runs don't collide
        # with real ones.
        IrAsset.env.registry.clear_cache()
        with patch.object(
            Manifest, "for_addon", lambda name, **kw: manifests.get(name)
        ):
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
        # No ``depends`` key => depends on base (``manif.get("depends") or
        # ["base"]``), so base must come first.
        manifests = {"base": {"depends": []}, "orphan": {}}
        order = self._sort(manifests, ["orphan", "base"])
        self.assertLess(order.index("base"), order.index("orphan"))


@tagged("post_install", "-at_install")
class TestAssetPathsCacheCanonical(TransactionCase):
    """IRASSET-P1: ``_get_asset_paths`` sorts the active-addons set before
    building the ``_topological_sort`` @ormcache key, so the key is canonical
    despite set hash randomization. Pin that the tuple is sorted, preventing
    cross-worker cache fragmentation.
    """

    def test_addons_are_sorted_into_topological_sort_key(self):
        IrAsset = self.env["ir.asset"]
        captured = []

        def spy_topo(_self, addons_tuple):
            captured.append(addons_tuple)
            return list(addons_tuple)

        cls = type(IrAsset)
        with (
            patch.object(
                cls,
                "_get_active_addons_list",
                lambda _self, **k: ["web", "base", "mail"],
            ),
            patch.object(
                cls, "_get_related_assets", lambda _self, domain, **k: IrAsset.browse()
            ),
            patch.object(cls, "_topological_sort", spy_topo),
        ):
            IrAsset._get_asset_paths("irasset_p1_probe.bundle", {})

        self.assertTrue(captured, "_topological_sort was invoked")
        self.assertEqual(captured[0], ("base", "mail", "web"))
