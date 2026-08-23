import logging
import re
from pathlib import Path

from odoo.modules import Manifest
from odoo.tests import tagged

from . import lint_case

_logger = logging.getLogger(__name__)

IMPORT_RE = re.compile(
    r"""(?:^|[\s;}])(?:import|export)\s+(?:[^'"()]*?\sfrom\s+)?["']([^"']+)["']""",
    re.MULTILINE,
)
REGISTRATION_RE = re.compile(
    r"^(?:onRpc|defineModels|defineParams|mockService)\(", re.MULTILINE
)
TEST_SUFFIX = ".test.js"


def _addon_js():
    for manifest in Manifest.all_addon_manifests():
        static_root = Path(manifest.path) / "static"
        if not static_root.is_dir():
            continue
        for path in static_root.rglob("*.js"):
            try:
                yield manifest.name, path, path.read_text(encoding="utf-8")
            except OSError, UnicodeDecodeError:
                continue


def _module_key(addon, path):
    """`<addon>/<posix path under static/>`, without the .js suffix."""
    parts = path.as_posix().split("/static/", 1)
    return f"{addon}/{parts[1].removesuffix('.js')}" if len(parts) == 2 else None


def _resolve(specifier, addon, path):
    spec = specifier.removesuffix(".js")
    if spec.startswith("@"):
        head, _, rest = spec[1:].partition("/")
        if rest.startswith("../"):
            return f"{head}/{rest[3:]}"
        return f"{head}/src/{rest}"
    if spec.startswith("."):
        here = path.as_posix().rsplit("/", 1)[0]
        resolved = Path(f"{here}/{spec}").resolve().as_posix()
        return _module_key(addon, Path(resolved))
    return None


@tagged("post_install", "-at_install")
class TestOrphanTestRegistrations(lint_case.LintCase):
    """A module-scope onRpc/defineModels registers through HOOT's `before()`,
    which attaches to the suite that is current when the call runs. A module the
    bundle evaluates but nobody imports has no current suite, so the call is
    accepted and dropped, and the mock it meant to install is simply absent.
    """

    def test_no_registration_module_is_orphaned(self):
        imported = set()
        candidates = {}
        scanned = 0
        for addon, path, source in _addon_js():
            scanned += 1
            imported.update(
                resolved
                for resolved in (
                    _resolve(spec, addon, path) for spec in IMPORT_RE.findall(source)
                )
                if resolved
            )
            posix = path.as_posix()
            if "/static/tests/" not in posix or posix.endswith(TEST_SUFFIX):
                continue
            if REGISTRATION_RE.search(source):
                key = _module_key(addon, path)
                if key:
                    candidates[posix] = key

        _logger.info(
            "scanned %s addon js file(s), %s carry a module-scope registration",
            scanned,
            len(candidates),
        )
        self.assertTrue(
            scanned,
            "no addon JS was scanned — the layout this gate walks has "
            "moved, and the gate is now vacuous",
        )
        orphans = sorted(p for p, key in candidates.items() if key not in imported)
        self.assertFalse(
            orphans,
            "test module(s) calling onRpc/defineModels at module scope that no "
            "other module imports; the bundle evaluates them outside any suite, "
            "so HOOT's `before()` has nothing to attach to and the registration "
            "is silently lost. Move the call into the helper the tests already "
            "invoke (defineXModels), not into an import — imports run before the "
            "module body, so the suite context is still absent:\n  "
            + "\n  ".join(orphans),
        )
