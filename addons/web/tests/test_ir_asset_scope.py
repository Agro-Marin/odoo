# Part of Odoo. See LICENSE file for full copyright and licensing details.

import re
from unittest.mock import patch

from odoo.modules import Manifest
from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.web.models.ir_asset import UNIT_TEST_URL_SEGMENT

BACKEND_BUNDLE = "web.assets_backend"
RUNNER_BUNDLE = "web.assets_unit_tests_setup"

#: A versioned bundle file link. Variant segments precede the version hash
#: (``/web/assets/scope/web/8eadcbf/web.assets_x.min.js``), so the path between
#: the prefix and the filename is matched loosely rather than as one hash.
CLASSIC_BUNDLE_LINK = re.compile(r"/web/assets/[\w/]+/[\w.]+\.min\.(?:js|css)")


def _declared_depends(addon):
    return set((Manifest.for_addon(addon) or {}).get("depends") or ["base"])


def _addon_of(entry):
    return entry.path.strip("/").partition("/")[0]


@tagged("post_install", "-at_install", "asset_scope")
class TestUnitTestAssetScope(TransactionCase):
    """``web.assets_unit_tests_setup`` scoping for HOOT runs.

    Without a scope the unit-test page executes every installed addon's
    ``src``, whose registry/patch side effects are global while mock models
    are opt-in per suite — so one addon's ``src`` reaches for models another
    addon's suite never defined.
    """

    def test_closure_follows_manifest_dependencies(self):
        """A dependency reached only through an intermediate is still included.

        Driven off a synthetic graph rather than a real addon: the property is
        about the walk, and every addon deep enough to exercise it (``mail``,
        which reaches ``base`` only via ``html_editor`` → ``bus`` → ``web``)
        sits *above* ``web`` in the dependency order, so it cannot be installed
        in the database ``web``'s own suite runs against.
        """
        graph = {
            "a": {"depends": ["b"]},
            "b": {"depends": ["c"]},
            "c": {"depends": ["base"]},
            "base": {"depends": []},
        }
        IrAsset = self.env["ir.asset"]

        with (
            patch.object(
                type(IrAsset),
                "_get_installed_addons_list",
                return_value=frozenset(graph),
            ),
            patch.object(Manifest, "for_addon", staticmethod(graph.get)),
        ):
            closure = IrAsset._get_unit_test_scope_addons("a")

        self.assertEqual(closure, frozenset(graph))

    def test_closure_is_transitive_over_installed_addons(self):
        """The closure is ``depends`` walked to a fixed point, not one hop.

        The direct list looks too narrow — ``mail`` declares only ``web_tour``
        and ``html_editor`` — but ``html_editor`` -> ``bus`` -> ``web`` ->
        ``base``, so the walk still covers what a suite's JS needs. Asserted as
        closure under the dependency relation over the addons this database
        actually carries: naming one example pinned a test in ``web`` to an
        addon ``web`` does not depend on, and it failed outright wherever that
        addon was not installed.
        """
        IrAsset = self.env["ir.asset"]
        installed = IrAsset._get_installed_addons_list()

        for addon in installed:
            closure = IrAsset._get_unit_test_scope_addons(addon)
            self.assertIn(addon, closure, f"{addon}: closure is not reflexive")
            self.assertLessEqual(
                closure, installed, f"{addon}: closure escapes the installed set"
            )
            for member in closure:
                self.assertLessEqual(
                    _declared_depends(member) & installed,
                    closure,
                    f"{addon}: closure stops at {member}'s dependencies instead "
                    "of walking through them",
                )

    def test_closure_excludes_addons_that_merely_depend_on_the_scope(self):
        """Depending *on* the scope does not put an addon in it.

        The relation is directed: what a suite's JS needs is what its addon
        depends on, and pulling the reverse direction in would restore exactly
        the foreign ``src`` the scope exists to keep out.
        """
        IrAsset = self.env["ir.asset"]
        installed = IrAsset._get_installed_addons_list()
        closure = IrAsset._get_unit_test_scope_addons("web")

        self.assertIn("web", closure)
        dependents = {a for a in installed if "web" in _declared_depends(a)} - {"web"}
        self.assertTrue(dependents, "no installed addon depends on web")
        self.assertFalse(dependents & closure)

    def test_uninstalled_scope_yields_no_addons(self):
        self.assertFalse(
            self.env["ir.asset"]._get_unit_test_scope_addons("no_such_addon")
        )

    def test_active_addons_are_narrowed_to_the_closure(self):
        IrAsset = self.env["ir.asset"]
        unscoped = set(IrAsset._get_active_addons_list())

        scoped = set(IrAsset._get_active_addons_list(unit_test_scope="web"))

        self.assertLessEqual(scoped, unscoped)
        self.assertIn("web", scoped)
        if "mail" in unscoped:
            self.assertNotIn("mail", scoped)

    def test_no_scope_leaves_the_addon_list_untouched(self):
        """The scope must be inert until a run asks for one."""
        IrAsset = self.env["ir.asset"]

        self.assertEqual(
            set(IrAsset._get_active_addons_list()),
            set(IrAsset._get_active_addons_list(unit_test_scope=None)),
        )

    def test_scope_is_ignored_outside_a_request(self):
        """No request (or a non-runner route) must not touch the cache key."""
        self.assertEqual(self.env["ir.asset"]._get_unit_test_scope(), "")
        self.assertNotIn("unit_test_scope", self.env["ir.asset"]._get_asset_params())


@tagged("post_install", "-at_install", "asset_scope")
class TestUnitTestAssetScopeResolution(TransactionCase):
    """What the scope does to a *resolved bundle*, not to the addon list.

    ``TestUnitTestAssetScope`` stops at ``_get_active_addons_list``. The claim
    the scope actually makes is about files -- "what cannot load cannot
    register" -- and a narrowed addon list only delivers that for the sources
    that are keyed by addon. These drive ``_get_asset_paths``, the last step
    before a bundle becomes bytes.
    """

    def setUp(self):
        super().setUp()
        IrAsset = self.env["ir.asset"]
        self.closure = IrAsset._get_unit_test_scope_addons("web")
        self.unscoped = IrAsset._get_asset_paths(BACKEND_BUNDLE, {})
        self.scoped = IrAsset._get_asset_paths(
            BACKEND_BUNDLE, {"unit_test_scope": "web"}
        )
        self.foreign_unscoped = [
            entry for entry in self.unscoped if _addon_of(entry) not in self.closure
        ]

    def test_manifest_declared_foreign_files_are_dropped(self):
        """The guarantee the scope does deliver, asserted on files.

        Every foreign file a *manifest* put in the bundle is gone once scoped:
        ``_get_manifest_assets`` is indexed by the narrowed addon list, so an
        addon outside the closure contributes no manifest directive at all.
        The foreign files that do survive are exactly the ones an ``ir.asset``
        row declares -- the leak
        ``test_ir_asset_records_escape_the_scope`` pins -- so this asserts the
        two sources separately instead of letting one mask the other.
        """
        if not self.foreign_unscoped:
            self.skipTest("no addon outside web's closure contributes to the bundle")
        record_paths = {
            asset.path.strip("/")
            for asset in self.env["ir.asset"]
            .sudo()
            .with_context(active_test=False)
            .search([])
        }
        surviving = {
            entry.path
            for entry in self.scoped
            if _addon_of(entry) not in self.closure
            and entry.path.strip("/") not in record_paths
        }

        self.assertFalse(
            surviving,
            f"scoped bundle still carries manifest-declared files {sorted(surviving)}",
        )

    def test_scope_removes_the_bulk_of_the_bundle(self):
        """A guard against the scope silently degrading to a no-op.

        The per-addon assertions above all pass vacuously if the scope stops
        narrowing anything at all -- a renamed asset param, an override that
        swallows the keyword -- and nothing else in this file would notice.
        """
        if not self.foreign_unscoped:
            self.skipTest("no addon outside web's closure contributes to the bundle")

        self.assertLess(len(self.scoped), len(self.unscoped))

    def test_an_ir_asset_record_cannot_escape_the_scope(self):
        """The source that carries no addon is gated too.

        ``_get_asset_paths`` narrows the *manifest* side by handing
        ``_get_manifest_assets`` the closure, but ``_fetch_bundle_assets``
        selects rows by bundle with no addon predicate at all -- a row names a
        path and nothing else. So the closure has to reach the one place that
        decides whether a path may resolve, ``Resolution.active``; while that
        was built from ``_get_installed_addons_list()`` this row landed in the
        bundle, and a glob spelt the same way pulled in 92 files.

        Not a hypothetical source: ``website`` ships ~100 rows aimed at
        ``web.*`` bundles, one of which (``s_badge/000_variables.scss`` into
        ``web._assets_primary_variables``) reached a ``web``-scoped
        ``web.assets_backend`` on every database with ``website`` installed.
        """
        if not self.foreign_unscoped:
            self.skipTest("no addon outside web's closure contributes to the bundle")
        smuggled = self.foreign_unscoped[0]
        self.assertNotIn(smuggled, self.scoped)

        self.env["ir.asset"].create(
            {
                "name": "scope leak probe",
                "bundle": BACKEND_BUNDLE,
                "path": smuggled.path,
            }
        )
        rescoped = self.env["ir.asset"]._get_asset_paths(
            BACKEND_BUNDLE, {"unit_test_scope": "web"}
        )

        self.assertNotIn(smuggled.path, [entry.path for entry in rescoped])

    def test_a_glob_record_cannot_expand_into_a_foreign_addon(self):
        """The shape that leaks a directory rather than a file.

        A row is free to spell its path as a wildcard, and ``_glob_static_file``
        expands it against the addon's ``static/`` tree -- so one row is worth
        as many files as the foreign addon happens to have.
        """
        if not self.foreign_unscoped:
            self.skipTest("no addon outside web's closure contributes to the bundle")
        foreign_addon = _addon_of(self.foreign_unscoped[0])

        self.env["ir.asset"].create(
            {
                "name": "scope glob leak probe",
                "bundle": BACKEND_BUNDLE,
                "path": f"{foreign_addon}/static/src/**/*.js",
            }
        )
        rescoped = self.env["ir.asset"]._get_asset_paths(
            BACKEND_BUNDLE, {"unit_test_scope": "web"}
        )

        self.assertFalse(
            [e.path for e in rescoped if _addon_of(e) == foreign_addon],
        )

    def test_the_scoped_url_names_the_scope_that_built_it(self):
        """A bundle URL has to describe its variant, not merely differ.

        ``unique`` is a SHA256 over the *result*, so a scoped and an unscoped
        bundle get different URLs -- which is enough to keep them from
        overwriting each other's attachment, and not enough to rebuild either.
        ``content_assets`` re-resolves from the URL alone, so while the scope
        was absent from it the route produced the unscoped bundle, saw a
        different version, and redirected there.
        """
        if not self.foreign_unscoped:
            self.skipTest("no addon outside web's closure contributes to the bundle")
        IrAsset = self.env["ir.asset"]
        scoped_params = {"unit_test_scope": "web"}
        unique = (
            self.env["ir.qweb"]
            ._get_asset_bundle(BACKEND_BUNDLE, assets_params=scoped_params)
            .get_version("js")
        )

        scoped_url = IrAsset._get_asset_bundle_url(
            f"{BACKEND_BUNDLE}.min.js", unique, scoped_params
        )
        plain_url = IrAsset._get_asset_bundle_url(
            f"{BACKEND_BUNDLE}.min.js", unique, {}
        )

        self.assertEqual(
            scoped_url,
            f"/web/assets/scope/web/{unique}/{BACKEND_BUNDLE}.min.js",
        )
        self.assertNotEqual(scoped_url, plain_url)

    def test_every_asset_param_contributes_a_url_segment(self):
        """The rule that keeps the URL rebuildable as params are added.

        ``_get_asset_params`` and ``_get_asset_url_segments`` are two halves of
        one contract: whatever the first adds to the resolution, the second has
        to put in the URL, or the route cannot reproduce that resolution. An
        override adding a key to one and forgetting the other reintroduces the
        silent redirect, so compare the two directly rather than enumerating
        the keys some installation happens to have.
        """
        IrAsset = self.env["ir.asset"]
        params = dict.fromkeys(IrAsset._get_asset_params(), "probe")
        params["unit_test_scope"] = "web"

        segments = IrAsset._get_asset_url_segments(params)

        for key, value in params.items():
            self.assertIn(
                value,
                segments,
                f"{key} changes the resolution but not the URL that serves it",
            )


@tagged("post_install", "-at_install", "asset_scope")
class TestUnitTestAssetScopeRoutes(HttpCase):
    """Which *requests* the scope covers.

    A scoped run is not one request but many: the runner page, the bundles it
    links, and the bundles its ``loadBundle`` calls fetch afterwards. The scope
    reaches the first as a query parameter, the second through the published
    URL, and the third through ``session_info['bundle_params']``. Miss any of
    them and the page loads foreign ``src`` anyway.
    """

    def test_the_linked_bundle_is_served_at_its_own_url(self):
        """The runner page's own links must resolve to the scoped bundle.

        The URL is minted by the scoped render and fetched by a later,
        unscoped request. While the scope lived only in ``unique``, that later
        request rebuilt the bundle unscoped and 303'd the browser to it -- so
        the scoped classic bundle was never served, never cached, and every
        page load paid a full re-resolution to produce a redirect.
        """
        self.authenticate("admin", "admin")
        page = self.url_open("/web/tests?module_scope=web")
        page.raise_for_status()
        links = set(CLASSIC_BUNDLE_LINK.findall(page.text))
        if not links:
            self.skipTest("scoped runner page links no classic bundle")

        served = {
            link: self.url_open(link, allow_redirects=False) for link in sorted(links)
        }

        for link, response in served.items():
            self.assertEqual(response.status_code, 200, f"{link} was not served")
        self.assertTrue(
            any("/scope/web/" in link for link in links),
            f"no link carries the scope: {sorted(links)}",
        )

    def test_lazily_loaded_bundles_inherit_the_scope(self):
        """``loadBundle`` targets are resolved for the run that asked for them.

        The HOOT UI loads ``web.assets_unit_tests_setup_ui`` this way and
        ``web``'s own ``src`` does it for every lazy library, all over
        ``/web/bundle`` -- a request ``_get_unit_test_scope`` used to refuse to
        recognise, so a scoped page pulled unscoped bundles at runtime.
        """
        unscoped = self.url_open(f"/web/bundle/{RUNNER_BUNDLE}")
        scoped = self.url_open(f"/web/bundle/{RUNNER_BUNDLE}?module_scope=web")
        unscoped.raise_for_status()
        scoped.raise_for_status()

        self.assertNotEqual(scoped.json(), unscoped.json())

    def test_the_runner_page_publishes_the_scope_to_loadbundle(self):
        """The channel the previous test depends on, asserted directly.

        ``assets.js`` copies every ``session_info['bundle_params']`` entry into
        the ``/web/bundle`` query string; nothing else on the page would carry
        the scope there, and a run whose page omits it degrades silently to
        unscoped lazy bundles.
        """
        self.authenticate("admin", "admin")
        page = self.url_open("/web/tests?module_scope=web")
        page.raise_for_status()

        self.assertIn('"module_scope": "web"', page.text)

    def test_the_route_and_the_url_builder_spell_the_scope_alike(self):
        """Two literals, because one of them has to be statically readable.

        The route path is spelt out instead of interpolated from
        ``UNIT_TEST_URL_SEGMENT`` so an AST reader can see it -- an f-string is
        a ``JoinedStr``, and writing it that way made the URL invisible to
        ``machine_doc_v1/factcheck.sh``'s route census, which counts a handler
        it cannot count a URL for. Duplication is the price; this is what stops
        the two copies drifting.
        """
        rule = next(
            rule
            for rule in self.env["ir.http"].routing_map().iter_rules()
            if rule.endpoint.routing["routes"][0].startswith("/web/assets/")
            and "scope" in rule.arguments
        )

        self.assertIn(f"/web/assets/{UNIT_TEST_URL_SEGMENT}/", str(rule))

    def test_an_unknown_scope_is_not_served(self):
        """The scoped route must not mint a cache entry per arbitrary string."""
        response = self.url_open(
            f"/web/assets/scope/__no_such_addon__/any/{RUNNER_BUNDLE}.min.js",
            allow_redirects=False,
        )

        self.assertEqual(response.status_code, 404)
