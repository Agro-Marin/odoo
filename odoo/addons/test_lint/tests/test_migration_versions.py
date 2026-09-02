"""A migration directory is named by the bare module version, never the series.

``MigrationManager`` accepts both spellings and expands the bare one itself:
``_convert_version("1.8")`` and ``_convert_version("19.0.1.8")`` are the same
string. What differs is the comparison ``_is_migration_applicable`` then makes.
The bare form takes the series-relative branch and compares only the tail of
the installed version; the prefixed form compares absolute versions. Inside one
series the two agree on every input -- measured over a 396-case matrix of
folder, installed and target versions, zero divergent. Across series they do
not: for an installed ``18.0.1.30`` and a folder ``1.8``, the bare spelling
skips a script the module has already run and the prefixed spelling runs it
again.

That is why the series prefix is the form this tree refuses. 67 of its
migration directories are upstream's, and several of them -- ``l10n_ch``'s
``11.1``, ``l10n_at``'s ``3.2`` -- carry pre-19.0 module versions whose whole
purpose is that series-relative comparison. Pinning them to 19.0 would re-run
tax updates on any database upgraded from an older series, so the convention
that can hold at zero for the whole tree is the bare one.

A directory pinned to an *older* series (``l10n_es/upgrades/15.0.5.0``) is a
different thing and is left alone: it names an absolute version on a multi-
series upgrade path, and stripping its prefix would activate a script that
does not run on a 19.0 database today.

The second gate is the silent half. A directory name the loader's own
``VERSION_RE`` does not match is skipped with a log line nobody reads, so a
migration that never runs looks exactly like one that ran and did nothing.
"""

import logging
from pathlib import Path

from odoo import release
from odoo.modules.migration import VERSION_RE

from . import lint_case

_logger = logging.getLogger(__name__)

MIGRATION_DIRECTORIES = ("migrations", "upgrades")
SERIES_PREFIX = release.major_version + "."


def version_directories():
    for root in lint_case.core_module_roots():
        for kind in MIGRATION_DIRECTORIES:
            base = Path(root) / kind
            if not base.is_dir():
                continue
            for entry in sorted(base.iterdir()):
                if entry.is_dir() and entry.name != "tests":
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
