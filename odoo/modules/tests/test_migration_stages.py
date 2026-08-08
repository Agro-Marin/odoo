"""A migration script whose name matches no stage must not vanish silently.

``migrate_module`` selects scripts by filename prefix
(``name.startswith(f"{stage}-")``), and ``_scripts_by_version`` globs ``*.py``.
Anything in between — ``pre_01.py``, ``Pre-01.py``, ``migrate.py`` — is
collected and then dropped by every stage, with no diagnostic. On an upgrade of
a populated database that is a migration nobody notices did not happen.

``risks.md`` R3 records staging as unenforced. The *semantic* half genuinely is:
nothing can know that a script reading the old schema was filed ``post-``. The
syntactic half is checkable, and these tests are the check.
"""

import logging

import pytest

from odoo.modules.migration import (
    MIGRATION_STAGES,
    _scripts_by_version,
    _warn_unstaged_scripts,
)


@pytest.fixture
def version_dir(tmp_path):
    d = tmp_path / "19.0.1.0"
    d.mkdir()
    return d


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


class TestUnstagedScriptsWarn:
    @pytest.mark.parametrize(
        "name",
        [
            "pre_01_typo.py",  # underscore instead of hyphen
            "Pre-01.py",  # the match is case-sensitive
            "migrate.py",  # no stage at all
            "0-first.py",  # numeric prefix, a plausible ordering idiom
        ],
    )
    def test_a_script_matching_no_stage_is_reported(self, version_dir, caplog, name):
        (version_dir / name).touch()
        with caplog.at_level(logging.WARNING):
            _warn_unstaged_scripts(version_dir, [str(version_dir / name)])
        messages = _warnings(caplog)
        assert len(messages) == 1, messages
        assert name in messages[0]
        assert "never run" in messages[0]

    @pytest.mark.parametrize("stage", MIGRATION_STAGES)
    def test_a_correctly_staged_script_is_silent(self, version_dir, caplog, stage):
        path = version_dir / f"{stage}-01-thing.py"
        path.touch()
        with caplog.at_level(logging.WARNING):
            _warn_unstaged_scripts(version_dir, [str(path)])
        assert _warnings(caplog) == []

    def test_dunder_init_is_not_a_migration_script(self, version_dir, caplog):
        """Packages beside the scripts are legitimate and must stay quiet."""
        path = version_dir / "__init__.py"
        path.touch()
        with caplog.at_level(logging.WARNING):
            _warn_unstaged_scripts(version_dir, [str(path)])
        assert _warnings(caplog) == []


class TestCollectionWiresTheWarning:
    def test_scripts_by_version_reports_while_collecting(self, tmp_path, caplog):
        """The warning must fire on the real collection path, not only in isolation."""
        version_dir = tmp_path / "19.0.1.0"
        version_dir.mkdir()
        (version_dir / "pre-01-good.py").touch()
        (version_dir / "post_02_bad.py").touch()

        with caplog.at_level(logging.WARNING):
            found = _scripts_by_version(str(tmp_path))

        assert sorted(p.rsplit("/", 1)[-1] for p in found["19.0.1.0"]) == [
            "post_02_bad.py",
            "pre-01-good.py",
        ], "collection itself must be unchanged — this only reports"
        messages = _warnings(caplog)
        assert len(messages) == 1, messages
        assert "post_02_bad.py" in messages[0]

    def test_an_empty_path_collects_nothing_and_says_nothing(self, caplog):
        with caplog.at_level(logging.WARNING):
            assert _scripts_by_version("") == {}
        assert _warnings(caplog) == []


class TestStagesAreDeclaredOnce:
    def test_the_stage_tuple_is_what_migrate_module_accepts(self):
        """``migrate_module``'s assert and the prefix list must not drift apart."""
        assert MIGRATION_STAGES == ("pre", "post", "end")
