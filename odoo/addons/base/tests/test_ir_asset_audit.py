import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from psycopg.errors import NotNullViolation

from odoo.exceptions import ValidationError
from odoo.modules import Manifest
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.base.models.ir_asset import (
    AssetPaths,
    Resolution,
    _glob_static_file,
)


@tagged("post_install", "-at_install")
class TestReplaceDirective(TransactionCase):
    """IRASSET-L1 / IRASSET-C2: pin the real ``IrAsset._process_path`` REPLACE
    branch. A present source is repositioned to the target slot (not dropped), a
    source set including the target keeps it, and sources land in source order
    (IRASSET-C2 — the old new-then-present order reordered interleaved sources).
    """

    @staticmethod
    def _paths(resolution):
        return [a.path for a in resolution.paths.list]

    def _seed(self, paths):
        resolution = Resolution(installed=set())
        resolution.paths.append([(p, "/full" + p, 1) for p in paths], "bundle1")
        return resolution

    def _run_replace(self, resolution, target_path, source_list):
        """Invoke the real _process_path REPLACE branch with resolution mocked."""
        IrAsset = self.env["ir.asset"]

        def fake_get_paths(_self, path_def, _resolution):
            if path_def == "TARGET":
                return [(target_path, "/full" + target_path, 1)]
            if path_def == "SOURCE":
                return list(source_list)
            return []

        with patch.object(type(IrAsset), "_get_paths", fake_get_paths):
            IrAsset._process_path(
                resolution.open_bundle("bundle1"),
                resolution,
                "replace",
                "TARGET",
                "SOURCE",
            )

    def test_replace_source_already_present(self):
        ap = self._seed(["/a", "/b", "/c"])
        self._run_replace(ap, "/c", [("/a", "/full/a", 1)])
        self.assertEqual(self._paths(ap), ["/b", "/a"])
        self.assertIn("/a", ap.paths.memo)
        self.assertNotIn("/c", ap.paths.memo)

    def test_replace_new_source(self):
        ap = self._seed(["/a", "/b", "/c"])
        self._run_replace(ap, "/c", [("/d", "/full/d", 1)])
        self.assertEqual(self._paths(ap), ["/a", "/b", "/d"])

    def test_replace_self_keeps_target(self):
        ap = self._seed(["/a", "/b", "/c"])
        self._run_replace(ap, "/c", [("/c", "/full/c", 1)])
        self.assertEqual(self._paths(ap), ["/a", "/b", "/c"])
        self.assertIn("/c", ap.paths.memo)

    def test_replace_empty_source_removes_target(self):
        ap = self._seed(["/a", "/b", "/c"])
        self._run_replace(ap, "/b", [])
        self.assertEqual(self._paths(ap), ["/a", "/c"])
        self.assertNotIn("/b", ap.paths.memo)

    def test_replace_preserves_source_order(self):
        ap = self._seed(["/a", "/b", "/T"])
        source = [
            ("/a", "/full/a", 1),
            ("/x", "/full/x", 1),
            ("/b", "/full/b", 1),
            ("/y", "/full/y", 1),
        ]
        self._run_replace(ap, "/T", source)
        self.assertEqual(self._paths(ap), ["/a", "/x", "/b", "/y"])
        self.assertNotIn("/T", ap.paths.memo)

    def test_replace_glob_including_target_keeps_target_and_orders_new(self):
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
        ap = self._seed()
        with self.assertRaises(ValueError) as cm:
            ap.index("/web/absent.js", "bundle1")
        self.assertIn("bundle1", str(cm.exception))
        self.assertIn("/web/absent.js", str(cm.exception))

    def test_remove_resolvable_absent_path_raises_with_bundle(self):
        ap = self._seed()
        with self.assertRaises(ValueError) as cm:
            ap.remove([("/web/absent.js", "/full/absent.js", 1)], "bundle1")
        self.assertIn("bundle1", str(cm.exception))
        self.assertEqual([a.path for a in ap.list], ["/web/a.js", "/web/b.js"])

    def test_replace_absent_target_raises_via_process_path(self):
        IrAsset = self.env["ir.asset"]
        resolution = Resolution(installed=set())
        resolution.paths = self._seed()

        def fake_get_paths(_self, path_def, _resolution):
            return [(path_def, "/full" + path_def, 1)]

        with patch.object(type(IrAsset), "_get_paths", fake_get_paths):
            with self.assertRaises(ValueError) as cm:
                IrAsset._process_path(
                    resolution.open_bundle("bundle1"),
                    resolution,
                    "replace",
                    "/web/absent.js",
                    "/web/x.js",
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
        installed = Resolution(installed=IrAsset._get_installed_addons_list())
        escaping = "/base/static/../../../../etc/passwd"
        with self.assertLogs("odoo.addons.base.models.ir_asset", level="WARNING") as cm:
            result = IrAsset._get_paths(escaping, installed)
        joined = "\n".join(cm.output)
        self.assertIn("resolves outside the static/", joined)
        self.assertEqual(result, [(escaping, None, None)])

    def test_missing_literal_inside_static_warns_typo(self):
        IrAsset = self.env["ir.asset"]
        installed = Resolution(installed=IrAsset._get_installed_addons_list())
        inside = "/base/static/src/scss/__does_not_exist__.scss"
        with self.assertLogs("odoo.addons.base.models.ir_asset", level="WARNING") as cm:
            result = IrAsset._get_paths(inside, installed)
        joined = "\n".join(cm.output)
        self.assertIn("matches no bundleable file in the static/", joined)
        self.assertNotIn("resolves outside the static/", joined)
        self.assertEqual(result, [(inside, None, None)])

    def test_existing_literal_inside_static_does_not_warn(self):
        IrAsset = self.env["ir.asset"]
        installed = Resolution(installed=IrAsset._get_installed_addons_list())
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
        resolution = Resolution(installed=set())
        ap = resolution.paths
        ap.append([("/a", "/f/a", 1), ("/b", "/f/b", 1), ("/c", "/f/c", 1)], "bundle1")

        def fake_get_paths(_self, path_def, _resolution):
            resolved = target if path_def == target else source_path
            return [(resolved, "/f" + resolved, 1)]

        with patch.object(type(IrAsset), "_get_paths", fake_get_paths):
            with self.assertLogs(
                "odoo.addons.base.models.ir_asset", level="WARNING"
            ) as cm:
                IrAsset._process_path(
                    resolution.open_bundle("bundle1"),
                    resolution,
                    directive,
                    target,
                    source_path,
                )
        return [a.path for a in ap.list], " ".join(cm.output)

    def test_after_present_source_warns_and_is_noop(self):
        paths, log = self._run("after", "/a", "/c")
        self.assertEqual(paths, ["/a", "/b", "/c"])
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
        resolution = Resolution(installed=set())
        resolution.paths = ap

        def fake_get_paths(_self, _path_def, _resolution):
            return resolved

        with patch.object(type(IrAsset), "_get_paths", fake_get_paths):
            IrAsset._process_path(
                resolution.open_bundle("bundle1"),
                resolution,
                "remove",
                None,
                path_def,
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
        manifests = {"base": {"depends": []}, "orphan": {}}
        order = self._sort(manifests, ["orphan", "base"])
        self.assertLess(order.index("base"), order.index("orphan"))


@tagged("post_install", "-at_install")
class TestAssetPathsCacheCanonical(TransactionCase):
    """IRASSET-P1: ``_get_asset_paths`` sorts the active-addons set before
    building the addon-keyed @ormcache key, so the key is canonical despite set
    hash randomization. Pin that the tuple is sorted, preventing cross-worker
    cache fragmentation.
    """

    def test_addons_are_sorted_into_manifest_index_key(self):
        IrAsset = self.env["ir.asset"]
        captured = []

        def spy_index(_self, addons):
            captured.append(addons)
            return {}

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
            patch.object(cls, "_get_manifest_assets", spy_index),
        ):
            IrAsset._get_asset_paths("irasset_p1_probe.bundle", {})

        self.assertTrue(captured, "_get_manifest_assets was invoked")
        self.assertEqual(captured[0], ("base", "mail", "web"))

    def test_topological_sort_key_is_the_sorted_tuple(self):
        """The index defers to ``_topological_sort`` with the same canonical key."""
        IrAsset = self.env["ir.asset"]
        captured = []

        def spy_topo(_self, addons_tuple):
            captured.append(addons_tuple)
            return ()

        with patch.object(type(IrAsset), "_topological_sort", spy_topo):
            IrAsset._get_manifest_assets.__wrapped__(IrAsset, ("base", "mail", "web"))

        self.assertEqual(captured, [("base", "mail", "web")])


@tagged("post_install", "-at_install")
class TestManifestAssetsIndex(TransactionCase):
    """The manifest scan is an index built once per addon set, not a rescan per
    bundle. Pin what the index must preserve: every declaration, grouped by
    bundle, in topological addon order.
    """

    def test_index_groups_commands_by_bundle_in_addon_order(self):
        IrAsset = self.env["ir.asset"]
        manifests = {
            "alpha": {"a.bundle": ["/alpha/one.js"], "b.bundle": ["/alpha/two.js"]},
            "beta": {"a.bundle": ["/beta/one.js", ["remove", "/alpha/one.js"]]},
        }

        class FakeManifest(dict):
            pass

        with (
            patch.object(
                type(IrAsset), "_topological_sort", lambda _s, addons: ("alpha", "beta")
            ),
            patch.object(
                Manifest,
                "for_addon",
                staticmethod(lambda name, **k: FakeManifest(assets=manifests[name])),
            ),
        ):
            index = IrAsset._get_manifest_assets.__wrapped__(IrAsset, ("alpha", "beta"))

        self.assertEqual(
            index["a.bundle"],
            (
                ("alpha", "/alpha/one.js"),
                ("beta", "/beta/one.js"),
                ("beta", ["remove", "/alpha/one.js"]),
            ),
        )
        self.assertEqual(index["b.bundle"], (("alpha", "/alpha/two.js"),))

    def test_a_malformed_command_does_not_break_the_include_prefetch(self):
        """The prefetch reads the same commands the walk will parse, so a
        malformed one must not crash it before ``_process_command`` can report
        it against its addon.
        """
        IrAsset = self.env["ir.asset"]
        for command in (123, None, {"path": "x"}, ["include"], ["include", "a", "b"]):
            with self.subTest(command=command):
                closure = IrAsset._included_bundles(
                    "probe.bundle", {"probe.bundle": (("an_addon", command),)}
                )
                self.assertEqual(closure, {"probe.bundle"})
        self.assertEqual(
            IrAsset._included_bundles(
                "probe.bundle",
                {"probe.bundle": (("an_addon", ["include", "other.bundle"]),)},
            ),
            {"probe.bundle", "other.bundle"},
        )

    def test_index_skips_addons_without_a_manifest(self):
        IrAsset = self.env["ir.asset"]
        with (
            patch.object(
                type(IrAsset), "_topological_sort", lambda _s, addons: ("ghost",)
            ),
            patch.object(Manifest, "for_addon", staticmethod(lambda name, **k: None)),
        ):
            self.assertEqual(
                IrAsset._get_manifest_assets.__wrapped__(IrAsset, ("ghost",)), {}
            )

    def test_a_broken_manifest_directive_names_its_addon(self):
        """A directive that cannot be applied aborts every page pulling the
        bundle, so the error has to say which manifest to go fix.
        """
        IrAsset = self.env["ir.asset"]
        broken = ["after", "/nowhere/absent.js", "/culprit/new.js"]

        with (
            patch.object(
                type(IrAsset),
                "_get_manifest_assets",
                lambda _s, addons: {"probe.bundle": (("culprit", broken),)},
            ),
            patch.object(
                type(IrAsset),
                "_get_paths",
                lambda _s, path_def, _resolution: [(path_def, "/full" + path_def, 1)],
            ),
            patch.object(
                type(IrAsset), "_get_related_assets", lambda _s, domain, **k: IrAsset
            ),
        ):
            with self.assertRaises(ValueError) as cm:
                IrAsset._get_asset_paths.__wrapped__(IrAsset, "probe.bundle", {})

        message = str(cm.exception)
        self.assertIn("culprit", message)
        self.assertIn("probe.bundle", message)
        self.assertIn("/nowhere/absent.js", message)


@tagged("post_install", "-at_install")
class TestCachedResultsAreImmutable(TransactionCase):
    """The ``assets`` ormcache hands the very same object to every later caller,
    so a consumer that mutated a returned collection would corrupt the cache for
    the whole worker. Pin that nothing mutable escapes.
    """

    def test_cached_accessors_return_immutable_collections(self):
        IrAsset = self.env["ir.asset"]
        self.assertIsInstance(IrAsset._get_asset_paths("web.assets_backend", {}), tuple)
        self.assertIsInstance(IrAsset._get_installed_addons_list(), frozenset)
        self.assertIsInstance(IrAsset._topological_sort(("base",)), tuple)

    def test_repeated_calls_return_the_identical_object(self):
        """Identity is the point: it is why mutability would be a cache bug."""
        IrAsset = self.env["ir.asset"]
        self.assertIs(
            IrAsset._get_asset_paths("web.assets_backend", {}),
            IrAsset._get_asset_paths("web.assets_backend", {}),
        )


@tagged("post_install", "-at_install")
class TestAssetsCacheInvalidatedAtCommit(TransactionCase):
    """Clearing the ``assets`` cache only at write time leaves it open to being
    repopulated from the pre-change rows before COMMIT, and that stale entry
    survives the commit because ``signal_changes`` only notifies *other*
    workers. Pin the post-commit re-clear that closes the window.
    """

    BUNDLE = "web.assets_backend"

    def _asset_cache_keys(self):
        return [
            key
            for key in self.env.registry.ormcache_lrus["assets"]
            if key[0] == "ir.asset" and "_get_asset_paths" in str(key[1])
        ]

    def _make_asset(self):
        return self.env["ir.asset"].create(
            {"name": "probe", "bundle": self.BUNDLE, "path": "/web/static/src/probe.js"}
        )

    def test_write_registers_a_post_commit_clear(self):
        self.env.cr.postcommit.clear()
        self._make_asset()
        self.assertTrue(
            self.env.cr.postcommit.data.get("ir_asset_cache_cleared"),
            "a post-commit clear must be queued",
        )
        self.assertEqual(len(self.env.cr.postcommit), 1)

    def test_post_commit_clear_evicts_an_entry_cached_before_commit(self):
        self.env.cr.postcommit.clear()
        self._make_asset()
        self.env["ir.asset"]._get_asset_paths(self.BUNDLE, {})
        self.assertTrue(self._asset_cache_keys(), "entry cached inside the txn")

        self.env.cr.postcommit.run()

        self.assertFalse(
            self._asset_cache_keys(),
            "the pre-commit entry must not outlive the commit",
        )

    def test_repeated_writes_queue_a_single_clear(self):
        self.env.cr.postcommit.clear()
        assets = self._make_asset()
        assets.write({"sequence": 5})
        assets.unlink()
        self.assertEqual(len(self.env.cr.postcommit), 1)


@tagged("post_install", "-at_install")
class TestDirectiveTargetValidation(TransactionCase):
    """A directive that cannot be applied is a data error, and belongs at write
    time. Left to render time it surfaces as a 500 on every page that pulls the
    bundle, with nothing pointing back at the offending record.
    """

    def test_positional_directive_requires_a_target(self):
        for directive in ("after", "before", "replace"):
            with self.subTest(directive=directive), self.assertRaises(ValidationError):
                self.env["ir.asset"].create(
                    {
                        "name": "no target",
                        "bundle": "probe.bundle",
                        "path": "/web/static/src/x.js",
                        "directive": directive,
                    }
                )

    def test_clearing_the_target_of_a_positional_directive_is_rejected(self):
        asset = self.env["ir.asset"].create(
            {
                "name": "with target",
                "bundle": "probe.bundle",
                "path": "/web/static/src/x.js",
                "directive": "after",
                "target": "/web/static/src/y.js",
            }
        )
        with self.assertRaises(ValidationError):
            asset.write({"target": False})

    def test_directive_cannot_be_blanked(self):
        """``directive`` is NOT NULL: a blank one used to reach _process_path and
        raise ``Unexpected directive: False`` while rendering the bundle.
        """
        asset = self.env["ir.asset"].create(
            {
                "name": "plain",
                "bundle": "probe.bundle",
                "path": "/web/static/src/x.js",
            }
        )
        with self.assertRaises(NotNullViolation):
            asset.write({"directive": False})
            asset.flush_recordset()

    def test_target_is_optional_for_non_positional_directives(self):
        asset = self.env["ir.asset"].create(
            {
                "name": "plain",
                "bundle": "probe.bundle",
                "path": "/web/static/src/x.js",
                "directive": "prepend",
            }
        )
        self.assertFalse(asset.target)


def _fake_get_paths(_self, path_def, _resolution):
    """Resolve every path definition to itself, one file, no filesystem."""
    return [(path_def, "/full" + path_def, 1)]


@tagged("post_install", "-at_install")
class TestPrependAnchor(TransactionCase):
    """``prepend`` inserts at the start of the segment the current bundle
    contributed. That start was captured as a plain index before any directive
    ran, so a directive that later removed something *in front of* it shifted
    the segment and left the index pointing one slot too far right — inside an
    ``include``, far enough to fall off the end and degrade to ``append``.
    """

    def _resolve(self, bundle, manifest_assets):
        IrAsset = self.env["ir.asset"]
        resolution = Resolution(
            installed=set(),
            manifest_assets={
                name: tuple(("an_addon", command) for command in commands)
                for name, commands in manifest_assets.items()
            },
        )
        with patch.object(type(IrAsset), "_get_paths", _fake_get_paths):
            IrAsset._fill_asset_paths(bundle, resolution, ())
        return [entry.path for entry in resolution.paths.list]

    def test_prepend_in_included_bundle_after_a_remove(self):
        paths = self._resolve(
            "t.outer",
            {
                "t.outer": ["/a.js", "/b.js", ["include", "t.inner"]],
                "t.inner": [["remove", "/a.js"], "/c.js", ["prepend", "/d.js"]],
            },
        )
        self.assertEqual(paths, ["/b.js", "/d.js", "/c.js"])

    def test_prepend_in_included_bundle_without_a_remove(self):
        paths = self._resolve(
            "t.outer",
            {
                "t.outer": ["/a.js", "/b.js", ["include", "t.inner"]],
                "t.inner": ["/c.js", ["prepend", "/d.js"]],
            },
        )
        self.assertEqual(paths, ["/a.js", "/b.js", "/d.js", "/c.js"])

    def test_prepend_stays_ahead_of_earlier_prepends(self):
        """Two prepends in one bundle keep the later one first, as before."""
        paths = self._resolve(
            "t.root", {"t.root": ["/a.js", ["prepend", "/b.js"], ["prepend", "/c.js"]]}
        )
        self.assertEqual(paths, ["/c.js", "/b.js", "/a.js"])

    def test_nested_includes_each_prepend_into_their_own_segment(self):
        paths = self._resolve(
            "t.a",
            {
                "t.a": ["/a.js", ["include", "t.b"], ["prepend", "/pa.js"]],
                "t.b": ["/b.js", ["include", "t.c"], ["prepend", "/pb.js"]],
                "t.c": ["/c.js", ["prepend", "/pc.js"]],
            },
        )
        self.assertEqual(
            paths, ["/pa.js", "/a.js", "/pb.js", "/b.js", "/pc.js", "/c.js"]
        )

    def test_prepend_in_root_bundle_after_a_remove(self):
        paths = self._resolve(
            "t.root",
            {"t.root": ["/a.js", "/b.js", ["remove", "/a.js"], ["prepend", "/c.js"]]},
        )
        self.assertEqual(paths, ["/c.js", "/b.js"])


@tagged("post_install", "-at_install")
class TestReplaceGlobTarget(TransactionCase):
    """A ``replace`` whose target is a glob designates every file the glob
    matched. Resolving the target to only its first match left every other
    matched file in the bundle: ``replace`` three files with one and two
    survived, silently, next to their replacement.
    """

    def _seed(self, paths):
        resolution = Resolution(installed=set())
        resolution.paths.append([(p, "/full" + p, 1) for p in paths], "bundle1")
        return resolution

    def _run_replace(self, resolution, target_def, targets, sources):
        IrAsset = self.env["ir.asset"]

        def fake_get_paths(_self, path_def, _resolution):
            resolved = targets if path_def == target_def else sources
            return [(p, "/full" + p, 1) for p in resolved]

        with patch.object(type(IrAsset), "_get_paths", fake_get_paths):
            IrAsset._process_path(
                resolution.open_bundle("bundle1"),
                resolution,
                "replace",
                target_def,
                "SOURCE",
            )
        return [entry.path for entry in resolution.paths.list]

    def test_every_matched_target_is_replaced(self):
        resolution = self._seed(["/f1.js", "/f2.js", "/keep.js"])
        paths = self._run_replace(
            resolution, "/f*.js", ["/f1.js", "/f2.js"], ["/new.js"]
        )
        self.assertEqual(paths, ["/new.js", "/keep.js"])

    def test_matches_absent_from_the_bundle_are_tolerated(self):
        """A glob resolves against disk; the bundle holds any subset of it."""
        resolution = self._seed(["/f2.js", "/keep.js"])
        paths = self._run_replace(
            resolution, "/f*.js", ["/f1.js", "/f2.js"], ["/new.js"]
        )
        self.assertEqual(paths, ["/new.js", "/keep.js"])

    def test_a_matched_target_that_is_also_a_source_survives(self):
        resolution = self._seed(["/f1.js", "/f2.js", "/keep.js"])
        paths = self._run_replace(
            resolution, "/f*.js", ["/f1.js", "/f2.js"], ["/new.js", "/f2.js"]
        )
        self.assertEqual(paths, ["/new.js", "/f2.js", "/keep.js"])

    def test_no_matched_target_present_still_raises(self):
        resolution = self._seed(["/keep.js"])
        with self.assertRaises(ValueError) as cm:
            self._run_replace(resolution, "/f*.js", ["/f1.js", "/f2.js"], ["/new.js"])
        self.assertIn("/f1.js", str(cm.exception))
        self.assertIn("bundle1", str(cm.exception))

    def test_anchor_follows_target_order_not_bundle_order(self):
        """The anchor is the first RESOLVED target the bundle holds, so it is
        decided by the target definition, not by how the bundle got ordered.
        """
        IrAsset = self.env["ir.asset"]
        resolution = self._seed(["/f2.js", "/f1.js", "/keep.js"])

        def fake_get_paths(_self, path_def, _resolution):
            resolved = ["/f1.js", "/f2.js"] if path_def == "/f*.js" else ["/new.js"]
            return [(p, "/full" + p, 1) for p in resolved]

        with patch.object(type(IrAsset), "_get_paths", fake_get_paths):
            IrAsset._process_path(
                resolution.open_bundle("bundle1"),
                resolution,
                "before",
                "/f*.js",
                "SOURCE",
            )
        self.assertEqual(
            [entry.path for entry in resolution.paths.list],
            ["/f2.js", "/new.js", "/f1.js", "/keep.js"],
        )

    def test_after_anchors_on_the_first_matched_target_present(self):
        """A positional directive anchors on a match the bundle actually has."""
        IrAsset = self.env["ir.asset"]
        resolution = self._seed(["/f2.js", "/keep.js"])

        def fake_get_paths(_self, path_def, _resolution):
            resolved = ["/f1.js", "/f2.js"] if path_def == "/f*.js" else ["/new.js"]
            return [(p, "/full" + p, 1) for p in resolved]

        with patch.object(type(IrAsset), "_get_paths", fake_get_paths):
            IrAsset._process_path(
                resolution.open_bundle("bundle1"),
                resolution,
                "after",
                "/f*.js",
                "SOURCE",
            )
        self.assertEqual(
            [entry.path for entry in resolution.paths.list],
            ["/f2.js", "/new.js", "/keep.js"],
        )


@tagged("post_install", "-at_install")
class TestDirectiveAttribution(TransactionCase):
    """A directive that cannot be applied aborts every page pulling the bundle.
    Manifest commands have always named their addon; an ``ir.asset`` row raised
    the same bare ``File(s) ... not found`` with nothing identifying the record,
    which is the only thing an admin can act on for a DB-authored directive.
    """

    BUNDLE = "attribution.probe"

    def _resolve(self):
        IrAsset = self.env["ir.asset"]
        with patch.object(type(IrAsset), "_get_paths", _fake_get_paths):
            IrAsset._get_asset_paths.__wrapped__(IrAsset, self.BUNDLE, {})

    def test_a_broken_record_names_itself(self):
        asset = self.env["ir.asset"].create(
            {
                "name": "the culprit",
                "bundle": self.BUNDLE,
                "directive": "after",
                "path": "/some/new.js",
                "target": "/some/absent.js",
            }
        )
        with self.assertRaises(ValueError) as cm:
            self._resolve()
        message = str(cm.exception)
        self.assertIn("the culprit", message)
        self.assertIn(str(asset.id), message)
        self.assertIn("/some/absent.js", message)
        self.assertIn(self.BUNDLE, message)

    def test_attribution_happens_once_across_includes(self):
        """The innermost declaration is named; outer frames re-raise as is."""
        self.env["ir.asset"].create(
            {
                "name": "outer include",
                "bundle": self.BUNDLE,
                "directive": "include",
                "path": "attribution.inner",
            }
        )
        self.env["ir.asset"].create(
            {
                "name": "inner culprit",
                "bundle": "attribution.inner",
                "directive": "before",
                "path": "/some/new.js",
                "target": "/some/absent.js",
            }
        )
        with self.assertRaises(ValueError) as cm:
            self._resolve()
        message = str(cm.exception)
        self.assertIn("inner culprit", message)
        self.assertNotIn("outer include", message)
        self.assertEqual(message.count("raised by"), 1)


@tagged("post_install", "-at_install")
class TestBundleAssetsFetch(TransactionCase):
    """Walking a bundle walks every bundle it includes, and each one used to
    issue its own ``ir.asset`` search. Fetching the whole table once instead
    trades those round-trips for a cost that grows with rows the bundle will
    never use, so the prefetch is bounded by the manifest include closure and
    anything an ``ir.asset`` include reveals is fetched on demand.
    """

    def _spy(self):
        IrAsset = self.env["ir.asset"]
        calls = []
        original = type(IrAsset)._get_related_assets

        def spy(inner_self, domain, **params):
            calls.append(domain)
            return original(inner_self, domain, **params)

        return calls, patch.object(type(IrAsset), "_get_related_assets", spy)

    def test_a_manifest_include_chain_costs_one_fetch(self):
        IrAsset = self.env["ir.asset"]
        manifest_assets = {
            f"chain.b{i}": (("an_addon", ["include", f"chain.b{i + 1}"]),)
            for i in range(4)
        }
        calls, spy = self._spy()
        with (
            spy,
            patch.object(
                type(IrAsset), "_get_manifest_assets", lambda _s, addons: manifest_assets
            ),
            patch.object(type(IrAsset), "_get_paths", _fake_get_paths),
        ):
            IrAsset._get_asset_paths.__wrapped__(IrAsset, "chain.b0", {})
        self.assertEqual(len(calls), 1, f"one fetch expected, got {calls}")
        self.assertEqual(
            sorted(calls[0][0][2]),
            ["chain.b0", "chain.b1", "chain.b2", "chain.b3", "chain.b4"],
        )

    def test_the_prefetch_does_not_read_unrelated_bundles(self):
        """The whole point of bounding it: rows of other bundles stay unread."""
        IrAsset = self.env["ir.asset"]
        IrAsset.create(
            {"name": "elsewhere", "bundle": "other.bundle", "path": "/some/x.js"}
        )
        calls, spy = self._spy()
        with (
            spy,
            patch.object(type(IrAsset), "_get_manifest_assets", lambda _s, a: {}),
            patch.object(type(IrAsset), "_get_paths", _fake_get_paths),
        ):
            IrAsset._get_asset_paths.__wrapped__(IrAsset, "lonely.bundle", {})
        self.assertEqual(calls, [[("bundle", "in", ["lonely.bundle"])]])

    def test_a_record_include_is_fetched_on_demand(self):
        """An include only a DB row knows about cannot be prefetched."""
        IrAsset = self.env["ir.asset"]
        IrAsset.create(
            {
                "name": "record include",
                "bundle": "rec.outer",
                "directive": "include",
                "path": "rec.inner",
            }
        )
        IrAsset.create(
            {"name": "leaf", "bundle": "rec.inner", "path": "/some/leaf.js"}
        )
        calls, spy = self._spy()
        with (
            spy,
            patch.object(type(IrAsset), "_get_manifest_assets", lambda _s, a: {}),
            patch.object(type(IrAsset), "_get_paths", _fake_get_paths),
        ):
            paths = IrAsset._get_asset_paths.__wrapped__(IrAsset, "rec.outer", {})
        self.assertEqual([entry.path for entry in paths], ["/some/leaf.js"])
        self.assertEqual(len(calls), 2, f"one prefetch + one on demand, got {calls}")

    def test_each_bundle_is_fetched_at_most_once(self):
        IrAsset = self.env["ir.asset"]
        resolution = Resolution(installed=set())
        calls, spy = self._spy()
        with spy:
            IrAsset._fetch_bundle_assets(resolution, ["a.b", "c.d"])
            IrAsset._fetch_bundle_assets(resolution, ["a.b"])
            IrAsset._fetch_bundle_assets(resolution, ["c.d", "e.f"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1], [("bundle", "in", ["e.f"])])

    def test_the_index_keeps_the_sequence_order(self):
        IrAsset = self.env["ir.asset"]
        for sequence in (30, 10, 20):
            IrAsset.create(
                {
                    "name": f"seq {sequence}",
                    "bundle": "order.probe",
                    "path": f"/some/f{sequence}.js",
                    "sequence": sequence,
                }
            )
        resolution = Resolution(installed=set())
        IrAsset._fetch_bundle_assets(resolution, ["order.probe"])
        self.assertEqual(
            [a.sequence for a in resolution.bundle_assets["order.probe"]], [10, 20, 30]
        )

    def test_inactive_records_are_left_out(self):
        IrAsset = self.env["ir.asset"]
        IrAsset.create(
            {
                "name": "off",
                "bundle": "active.probe",
                "path": "/some/off.js",
                "active": False,
            }
        )
        resolution = Resolution(installed=set())
        IrAsset._fetch_bundle_assets(resolution, ["active.probe"])
        self.assertNotIn("active.probe", resolution.bundle_assets)


@tagged("post_install", "-at_install")
class TestStaticContainment(TransactionCase):
    """Containment is decided lexically against the addon root, so a symlink is
    no longer collapsed before the check. Crossing one must still be allowed
    when it lands back inside ``static/`` — that is what the previous
    ``Path(...).resolve()`` did, and vendored libraries are symlinked that way —
    while landing outside must be refused whether a literal path names the link
    or a wildcard expands onto it.
    """

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.static = Path(self.tmp, "an_addon", "static")
        (self.static / "src" / "real").mkdir(parents=True)
        (self.static / "src" / "real" / "in.js").write_text("var a;")
        self.outside = Path(self.tmp, "elsewhere")
        self.outside.mkdir()
        (self.outside / "secret.js").write_text("var s;")
        Path(self.static, "src", "linked").symlink_to(self.static / "src" / "real")
        Path(self.static, "src", "escape").symlink_to(self.outside)
        Path(self.static, "src", "file_link.js").symlink_to(
            self.static / "src" / "real" / "in.js"
        )

    def _glob(self, pattern):
        return [
            os.path.relpath(path, self.static)
            for path, _mtime in _glob_static_file(
                str(self.static / pattern), str(self.static)
            )
        ]

    def test_symlink_landing_inside_static_is_followed(self):
        self.assertEqual(self._glob("src/linked/in.js"), ["src/real/in.js"])
        self.assertEqual(self._glob("src/linked/*.js"), ["src/real/in.js"])
        self.assertEqual(self._glob("src/file_link.js"), ["src/real/in.js"])

    def test_symlink_landing_outside_static_is_refused(self):
        with self.assertLogs("odoo.addons.base.models.ir_asset", level="WARNING"):
            self.assertEqual(self._glob("src/escape/secret.js"), [])
        with self.assertLogs("odoo.addons.base.models.ir_asset", level="WARNING"):
            self.assertEqual(self._glob("src/escape/*.js"), [])

    def test_a_link_and_its_target_collapse_to_one_entry(self):
        """Both spellings resolve to the same file; the bundle must see it once."""
        self.assertEqual(self._glob("src/*/*.js"), ["src/real/in.js"])


@tagged("post_install", "-at_install")
class TestPerBundleFiltering(TransactionCase):
    """Arbitration between records competing for the same slot is applied per
    bundle, not per batch. The batched fetch spans a whole include closure, so
    filtering it as one set would let a record of one bundle suppress a record
    of another -- which is exactly what website's generic/specific ``key``
    matching does.
    """

    def test_the_hook_sees_one_bundle_at_a_time(self):
        IrAsset = self.env["ir.asset"]
        for bundle in ("split.a", "split.b"):
            for index in (1, 2):
                IrAsset.create(
                    {
                        "name": f"{bundle} {index}",
                        "bundle": bundle,
                        "path": f"/some/{bundle}_{index}.js",
                    }
                )
        seen = []
        original = type(IrAsset)._filter_bundle_assets

        def spy(inner_self, assets, **params):
            seen.append(sorted(assets.mapped("bundle")))
            return original(inner_self, assets, **params)

        resolution = Resolution(installed=set())
        with patch.object(type(IrAsset), "_filter_bundle_assets", spy):
            IrAsset._fetch_bundle_assets(resolution, ["split.a", "split.b"])

        self.assertEqual(
            sorted(seen), [["split.a", "split.a"], ["split.b", "split.b"]]
        )
        self.assertEqual(len(resolution.bundle_assets["split.a"]), 2)
        self.assertEqual(len(resolution.bundle_assets["split.b"]), 2)

    def test_the_hook_can_drop_records(self):
        IrAsset = self.env["ir.asset"]
        IrAsset.create(
            {"name": "kept", "bundle": "drop.probe", "path": "/some/kept.js"}
        )
        IrAsset.create(
            {"name": "dropped", "bundle": "drop.probe", "path": "/some/dropped.js"}
        )
        resolution = Resolution(installed=set())
        with patch.object(
            type(IrAsset),
            "_filter_bundle_assets",
            lambda _s, assets, **p: assets.filtered(lambda a: a.name == "kept"),
        ):
            IrAsset._fetch_bundle_assets(resolution, ["drop.probe"])
        self.assertEqual(
            [a.name for a in resolution.bundle_assets["drop.probe"]], ["kept"]
        )


@tagged("post_install", "-at_install")
class TestInvalidationIsNarrow(TransactionCase):
    """Dropping the ``assets`` cache costs every bundle its resolution, so only
    a write that can change what a bundle resolves to may do it. Renaming a
    record cannot.
    """

    BUNDLE = "narrow.probe"

    def _cached_keys(self):
        return [
            key
            for key in self.env.registry.ormcache_lrus["assets"]
            if key[0] == "ir.asset" and "_get_asset_paths" in str(key[1])
        ]

    def _warm(self, asset):
        self.env.registry.clear_cache("assets")
        self.env["ir.asset"]._get_asset_paths(self.BUNDLE, {})
        self.assertTrue(self._cached_keys(), "cache should be warm")

    def _make(self):
        return self.env["ir.asset"].create(
            {"name": "probe", "bundle": self.BUNDLE, "path": "/some/probe.js"}
        )

    def test_renaming_keeps_the_cache(self):
        asset = self._make()
        self._warm(asset)
        asset.write({"name": "renamed"})
        self.assertTrue(self._cached_keys(), "a rename must not drop the cache")

    def test_every_resolution_field_drops_the_cache(self):
        asset = self._make()
        for field, value in (
            ("path", "/some/other.js"),
            ("bundle", "narrow.other"),
            ("sequence", 99),
            ("directive", "prepend"),
            ("active", False),
        ):
            with self.subTest(field=field):
                asset.write({"bundle": self.BUNDLE, "active": True})
                self._warm(asset)
                asset.write({field: value})
                self.assertFalse(
                    self._cached_keys(), f"writing {field} must drop the cache"
                )

    def test_target_counts_as_a_resolution_field(self):
        """It is only read for positional directives, but it is read."""
        self.assertIn("target", self.env["ir.asset"]._resolution_fields())


@tagged("post_install", "-at_install")
class TestExternalUrlShortCircuit(TransactionCase):
    """A URL that cannot be aggregated is decided by its own spelling. Looking
    up an addon manifest first only mattered for paths that can be bundled, and
    a miss there walks every addons path attempting to open a manifest file.
    """

    def test_an_external_url_never_consults_a_manifest(self):
        IrAsset = self.env["ir.asset"]
        resolution = Resolution(installed=IrAsset._get_installed_addons_list())
        for url in (
            "http://external.link/external.js",
            "https://cdn.example.com/a.css",
            "//cdn.example.com/b.js",
            "/web/content/1234/some.js",
        ):
            with self.subTest(url=url):
                resolved = IrAsset._get_paths(url, resolution)
                self.assertEqual(len(resolved), 1)
                self.assertTrue(resolved[0].is_external)
                self.assertEqual(resolved[0].path, url)
        self.assertEqual(
            resolution._manifests, {}, "no manifest lookup should have happened"
        )

    def test_a_bundleable_path_still_resolves(self):
        IrAsset = self.env["ir.asset"]
        resolution = Resolution(installed=IrAsset._get_installed_addons_list())
        resolved = IrAsset._get_paths(
            "/base/static/src/scss/res_users.scss", resolution
        )
        self.assertEqual(len(resolved), 1)
        self.assertFalse(resolved[0].is_external)
        self.assertIn("base", resolution._manifests)


@tagged("post_install", "-at_install")
class TestUnservableBundleNameWarns(TransactionCase):
    """``_parse_bundle_name`` demands exactly one dot, so any other spelling
    resolves fine and then 404s. Warn rather than raise: a bundle reached only
    through ``include`` is never parsed as a filename, so it is unconventional
    rather than invalid.
    """

    def test_a_dotless_bundle_warns(self):
        with self.assertLogs("odoo.addons.base.models.ir_asset", level="WARNING") as cm:
            self.env["ir.asset"].create(
                {"name": "probe", "bundle": "no_dot", "path": "/some/x.js"}
            )
        self.assertIn("no_dot", " ".join(cm.output))
        self.assertIn("<addon>.<name>", " ".join(cm.output))

    def test_a_conforming_bundle_is_silent(self):
        with self.assertNoLogs("odoo.addons.base.models.ir_asset", level="WARNING"):
            self.env["ir.asset"].create(
                {"name": "probe", "bundle": "an_addon.a_bundle", "path": "/some/x.js"}
            )

    def test_the_warning_matches_what_the_parser_accepts(self):
        IrAsset = self.env["ir.asset"]
        for bundle in ("one.dot",):
            IrAsset._parse_bundle_name(f"{bundle}.min.js", False)
        for bundle in ("no_dot", "three.dots.here"):
            with self.assertRaises(ValueError):
                IrAsset._parse_bundle_name(f"{bundle}.min.js", False)


@tagged("post_install", "-at_install")
class TestAssetsCacheStores(TransactionCase):
    """Resolved file lists and the URL lists derived from them live in sibling
    LRUs of one clear group. They used to share a single 512-slot store, where
    the URL lists -- keyed on six values instead of two, so ~4x as many entries
    at ~1/742 the size -- evicted the resolutions they come from, each ~43 ms
    to rebuild. A single-website install already filled 415 of the 512 slots.
    """

    BUNDLES = ["cachestore.a", "cachestore.b", "cachestore.c"]

    def _lrus(self):
        return self.env.registry.ormcache_lrus

    def test_the_two_stores_are_separate_and_sized_apart(self):
        lrus = self._lrus()
        self.assertIn("assets", lrus)
        self.assertIn("assets.links", lrus)
        self.assertIsNot(lrus["assets"], lrus["assets.links"])
        self.assertGreater(lrus["assets.links"].count, lrus["assets"].count)

    def test_variants_multiply_only_the_sibling_store(self):
        """Every (css/js, rtl, autoprefix) combination of one bundle is another
        URL entry but the same resolution, so the variants used to crowd out
        resolutions at 8:1 in a store they shared.
        """
        IrQweb = self.env["ir.qweb"]
        self.env.registry.clear_cache("assets")
        for bundle in self.BUNDLES:
            for css, js in ((True, False), (False, True)):
                for rtl in (False, True):
                    for autoprefix in (False, True):
                        IrQweb._generate_asset_links_cache(
                            bundle,
                            css=css,
                            js=js,
                            assets_params={},
                            rtl=rtl,
                            autoprefix=autoprefix,
                        )
        resolutions = len(self._lrus()["assets"])
        urls = len(self._lrus()["assets.links"])
        self.assertEqual(
            resolutions,
            len(self.BUNDLES),
            "one resolution per bundle, whatever the variant count",
        )
        self.assertEqual(urls, len(self.BUNDLES) * 8)
        self.assertGreater(
            urls,
            resolutions,
            "the many cheap entries no longer occupy the resolution store",
        )

    def test_clearing_the_group_still_drops_both(self):
        IrAsset = self.env["ir.asset"]
        IrQweb = self.env["ir.qweb"]
        IrAsset._get_asset_paths(self.BUNDLES[0], {})
        IrQweb._generate_asset_links_cache(
            self.BUNDLES[0], css=True, js=False, assets_params={}
        )
        self.assertTrue(self._lrus()["assets"])
        self.assertTrue(self._lrus()["assets.links"])

        self.env["ir.asset"].create(
            {"name": "probe", "bundle": self.BUNDLES[0], "path": "/some/x.js"}
        )

        self.assertFalse(self._lrus()["assets"])
        self.assertFalse(self._lrus()["assets.links"])

    def test_the_sibling_is_not_a_clear_group_of_its_own(self):
        with self.assertRaises(ValueError):
            self.env.registry.clear_cache("assets.links")
