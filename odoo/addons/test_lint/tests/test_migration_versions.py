import logging
from pathlib import Path

from odoo import release
from odoo.modules.migration import VERSION_RE

from . import lint_case

_logger = logging.getLogger(__name__)

MIGRATION_DIRECTORIES = ("migrations", "upgrades")
SERIES_PREFIX = release.major_version + "."


def _holds_something_git_can_track(entry):
    return any(child.name != "__pycache__" for child in entry.iterdir())


def version_directories():
    for root in lint_case.core_module_roots():
        for kind in MIGRATION_DIRECTORIES:
            base = Path(root) / kind
            if not base.is_dir():
                continue
            for entry in sorted(base.iterdir()):
                if (
                    entry.is_dir()
                    and entry.name != "tests"
                    and _holds_something_git_can_track(entry)
                ):
                    yield entry


class TestMigrationVersionDirectories(lint_case.LintCase):
    def test_no_migration_directory_carries_the_series_prefix(self):
        directories = list(version_directories())
        self.assertTrue(directories, "no migration directory was found at all")
        _logger.info("scanned %s migration directory(ies)", len(directories))
        self.assert_ratchet(
            [str(d) for d in directories if d.name.startswith(SERIES_PREFIX)],
            "lint_migration_series_prefix",
            f"migration directory(ies) prefixed with {release.major_version}",
            "Rename the directory to the bare module version. The loader "
            "prefixes it with the running series itself, and the bare form is "
            "the one that stays correct across a series upgrade.",
        )

    def test_every_migration_directory_is_one_the_loader_reads(self):
        self.assert_ratchet(
            [str(d) for d in version_directories() if not VERSION_RE.match(d.name)],
            "lint_migration_version_unreadable",
            "migration directory(ies) the loader skips",
            "MigrationManager matches a directory name against VERSION_RE and "
            "ignores what it cannot parse, so the scripts inside never run. "
            "Name it `x.y`, `x.y.z`, or those prefixed with a series.",
        )
