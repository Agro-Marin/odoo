import logging

from odoo import SUPERUSER_ID, api
from odoo.modules.registry import Registry
from odoo.tests import tagged
from odoo.tests.common import get_db_name

from . import lint_case

_logger = logging.getLogger(__name__)


@tagged("post_install", "-at_install")
class TestBundlesAssemble(lint_case.LintCase):
    def test_every_declared_bundle_assembles(self):
        """Every bundle any installed manifest declares must resolve.

        ``test_asset_paths_exist`` checks a manifest path against **disk**. That
        is a different question from whether the bundle can be built, and the
        gap between them is where a whole bundle dies:

            ("remove", "web/static/src/webclient/debug/debug_menu.js")

        The file exists, so the path check passes. It is no longer *in*
        ``web.assets_frontend``, so assembling that bundle raises
        ``AssetDirectiveError`` and the frontend serves nothing. Moving a file
        between two directories is enough to cause it, because membership is
        decided by path glob and every ``remove`` names its target by path.

        The two ``remove`` forms fail differently, which is what makes this hard
        to reason about and easy to check:

        - an explicit path whose target is absent from the bundle **raises**;
        - a glob matching nothing in the bundle is tolerated silently.

        So the same edit is fatal or invisible depending on which form the
        manifest happened to use, and only one of the two leaves evidence.

        Resolving each bundle is the whole check: ``_get_asset_paths`` applies
        every directive in order and raises on the first one that cannot be
        satisfied. No reimplementation of directive semantics, and it covers
        ``include`` cycles and unknown-bundle references for free.

        Written after ``web.assets_frontend`` was broken exactly this way while
        relocating ``services/debug/`` to ``webclient/debug/``: 577 entries one
        commit, an exception the next, and nothing between the two that could
        see it.

        **Served bundles only, not every declared one.** A fragment is not
        assemblable on its own and is not meant to be: ``web._dark_mode_variables``
        carries ``("before", "…/primitives.scss", "…/primitives.dark.scss")``
        for a file that arrives with ``web.assets_web``, so resolving it
        standalone raises although nothing is wrong. Judging every declared
        bundle reports that as a failure — this test did, on its first run.
        Resolving what is actually served covers the fragments anyway, since a
        served bundle walks everything it includes.
        """
        failures = []
        with Registry(get_db_name()).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            bundles = self.served_bundle_names(env)

            self.assertTrue(bundles, "no bundles found — the scan reached nothing")

            ir_asset = env["ir.asset"]
            params = ir_asset._get_asset_params()
            for bundle in bundles:
                try:
                    ir_asset._get_asset_paths(bundle, params)
                except Exception as exc:
                    failures.append(f"  {bundle}: {type(exc).__name__}: {exc}")

        self.assertFalse(
            failures,
            f"{len(failures)} of {len(bundles)} declared bundle(s) do not "
            "assemble:\n" + "\n".join(failures),
        )
        _logger.info("%s served bundles assemble", len(bundles))
