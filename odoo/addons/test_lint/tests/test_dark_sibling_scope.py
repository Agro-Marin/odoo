import logging

from odoo import SUPERUSER_ID, api
from odoo.modules.registry import Registry
from odoo.tests import tagged
from odoo.tests.common import get_db_name

from . import lint_case

_logger = logging.getLogger(__name__)

DARK_SUFFIX = ".dark.scss"

DARK_MARKER = "web/static/src/scss/primitives.dark.scss"

ALLOWED = set()


@tagged("post_install", "-at_install")
class TestDarkSiblingScope(lint_case.LintCase):
    """A ``*.dark.scss`` belongs only in a bundle that compiled the dark palette.

    A dark sibling is not inert in a light bundle. It is plain SCSS with no
    scheme guard of its own -- the guard is *which bundle it is in* -- so a
    light bundle compiles it against the light palette and lets it override the
    very file it was written to answer. Whether the override then wins is down
    to source order, which is worse than either outcome: it is not a decision
    anyone made. In project sharing, badge labels came out at #aeaeae on a
    light badge instead of #3c3c3c; on the frontend, the emoji picker took the
    dark placeholder opacity and search-contour border.

    Nothing else catches it. The bundle builds, the manifest paths all exist,
    the file is valid SCSS, and comparing the light and dark bundles to their
    own baselines shows no change -- both were wrong the same way before. It
    reaches a light bundle by glob, never by name, which is why grepping for
    the filename finds nothing.

    Found on web.assets_frontend, web.assets_frontend_lazy,
    portal.assets_chatter_style, project.webclient (seventeen of them),
    web.assets_web, web.assets_web_print and
    im_livechat.embed_assets_unit_tests_setup -- and on
    web.dark_mode_assets_backend, a bundle name nothing defines or serves,
    where iap_mail's dark sibling had been sitting undelivered.
    """

    def test_dark_siblings_only_in_dark_bundles(self):
        offenders = []
        checked = 0
        empty = []
        skipped = []
        with Registry(get_db_name()).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            for bundle in self.served_bundle_names(env):
                try:
                    files = env["ir.qweb"]._get_asset_bundle(bundle, css=True).files
                except Exception as exc:
                    skipped.append(f"{bundle} ({type(exc).__name__})")
                    continue
                if not files:
                    empty.append(bundle)
                    continue
                checked += 1
                urls = [(f["url"] or "").lstrip("/") for f in files]
                if DARK_MARKER in urls:
                    continue
                offenders.extend(
                    f"{bundle}: {url}"
                    for url in urls
                    if url.endswith(DARK_SUFFIX) and (bundle, url) not in ALLOWED
                )

        _logger.info("checked %s bundles with files", checked)
        self.assertFalse(
            skipped,
            f"{len(skipped)} served bundle(s) did not assemble, so this check "
            f"never looked at them; `TestBundlesAssemble` owns that:\n  "
            + "\n  ".join(skipped),
        )
        self.assertFalse(
            empty,
            f"{len(empty)} served bundle(s) assembled to no files:\n  "
            + "\n  ".join(empty),
        )
        self.assertFalse(
            offenders,
            f"{len(offenders)} dark sibling(s) in a bundle that never compiled "
            f"the dark palette. Exclude them with a `remove` directive, and "
            f"name them back in the matching dark bundle if they belong to "
            f"one:\n  " + "\n  ".join(offenders),
        )
