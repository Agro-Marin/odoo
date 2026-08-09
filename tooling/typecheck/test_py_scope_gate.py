#!/usr/bin/env python3
"""Self-test for py_scope_gate.py. Stdlib unittest; no Odoo import, no database.

Run: ``python tooling/typecheck/test_py_scope_gate.py``

Two things are tested, and the second is the point. That the gate reports the
committed state consistently is table stakes; that it **fails on the drift the
count ratchet cannot see** is the reason the file exists, so that scenario is
pinned by name rather than left to a coverage number.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import py_scope_gate as gate

ORM = "odoo/orm"


def log(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def parsing(path: str, module: str = "odoo.orm.x") -> str:
    """As mypy --verbose emits it: absolute, under the repo, module in parens."""
    return f"LOG:  Parsing {(gate.REPO / path).as_posix()} ({module})"


def error(path: str, code: str = "[arg-type]", line: int = 1) -> str:
    return f"{path}:{line}:1: error: Something is wrong  {code}"


class ParseLog(unittest.TestCase):
    def test_reads_errors_and_checked_files(self) -> None:
        errors, checked = gate.parse_log(
            log(
                parsing(f"{ORM}/models/base.py"),
                error(f"{ORM}/models/base.py"),
                error(f"{ORM}/models/base.py", "[var-annotated]"),
            )
        )
        self.assertEqual(checked, {f"{ORM}/models/base.py"})
        self.assertEqual(
            errors[f"{ORM}/models/base.py"], {"[arg-type]": 1, "[var-annotated]": 1}
        )

    def test_absolute_paths_normalise_to_repo_relative(self) -> None:
        absolute = (gate.REPO / ORM / "fields/textual.py").as_posix()
        errors, _ = gate.parse_log(log(error(absolute)))
        self.assertIn(f"{ORM}/fields/textual.py", errors)

    def test_a_path_quoted_inside_a_message_is_not_an_error_site(self) -> None:
        """Anchoring matters: an unanchored search misattributes the error."""
        errors, _ = gate.parse_log(
            log(f'{ORM}/db.py:3:1: error: Cannot find "{ORM}/other.py"  [misc]')
        )
        self.assertEqual(list(errors), [f"{ORM}/db.py"])

    def test_a_followed_import_outside_the_repo_is_not_scoped(self) -> None:
        """follow_imports=silent parses site-packages; none of it is ours to gate."""
        _, checked = gate.parse_log(
            log("LOG:  Parsing /usr/lib/python3.14/json/decoder.py (json.decoder)")
        )
        self.assertEqual(checked, set())

    def test_out_of_scope_packages_are_ignored(self) -> None:
        errors, checked = gate.parse_log(
            log(parsing("odoo/tools/misc.py"), error("odoo/tools/misc.py"))
        )
        self.assertEqual((errors, checked), ({}, set()))

    def test_a_log_without_verbose_is_a_usage_error_not_a_failure(self) -> None:
        """Every file would read as `unchecked` — failing for the wrong reason."""
        with tempfile.NamedTemporaryFile(
            "w", suffix=".log", delete=False, encoding="utf8"
        ) as handle:
            handle.write(log(error(f"{ORM}/models/base.py")))
        self.assertEqual(gate.main(["--log", handle.name, "--check"]), gate.EXIT_USAGE)


class Verdicts(unittest.TestCase):
    """Every verdict, on a synthetic tree so this checkout's debt cannot leak in."""

    def evaluate(self, **kwargs):
        base = {
            "package": "orm",
            "errors": {},
            "checked": {f"{ORM}/a.py", f"{ORM}/b.py"},
            "exempt": [],
            "budgets": {},
            "on_disk": {f"{ORM}/a.py", f"{ORM}/b.py"},
        }
        return gate.evaluate_package(**{**base, **kwargs})

    def test_clean_tree_passes(self) -> None:
        verdict = self.evaluate()
        self.assertEqual(verdict.failures, 0)
        self.assertEqual((verdict.locked, verdict.excepted), (2, 0))

    def test_regressed_when_an_unexcepted_file_errors(self) -> None:
        verdict = self.evaluate(errors={f"{ORM}/a.py": {"[arg-type]": 1}})
        self.assertEqual(verdict.regressed, [f"{ORM}/a.py"])

    def test_excepted_file_may_error_up_to_its_ceiling(self) -> None:
        verdict = self.evaluate(
            errors={f"{ORM}/a.py": {"[arg-type]": 3}},
            exempt=[f"{ORM}/a.py"],
            budgets={f"{ORM}/a.py": 3},
        )
        self.assertEqual(verdict.failures, 0)

    def test_over_budget_when_an_excepted_file_gets_worse(self) -> None:
        verdict = self.evaluate(
            errors={f"{ORM}/a.py": {"[arg-type]": 4}},
            exempt=[f"{ORM}/a.py"],
            budgets={f"{ORM}/a.py": 3},
        )
        self.assertEqual(verdict.over_budget, [(f"{ORM}/a.py", 4, 3)])

    def test_cleared_when_an_excepted_file_becomes_clean(self) -> None:
        """Shrink-only: a fixed file must leave the list, or it rots into an allowlist."""
        verdict = self.evaluate(exempt=[f"{ORM}/a.py"], budgets={f"{ORM}/a.py": 3})
        self.assertEqual(verdict.cleared, [f"{ORM}/a.py"])

    def test_stale_when_an_excepted_path_leaves_disk(self) -> None:
        """The rename hole — the failure mode that emptied ui_service.js's lock."""
        verdict = self.evaluate(exempt=[f"{ORM}/renamed.py"])
        self.assertEqual(verdict.stale, [f"{ORM}/renamed.py"])

    def test_out_of_scope_when_a_list_holds_another_package_s_path(self) -> None:
        verdict = self.evaluate(
            exempt=["odoo/db/pool.py"], on_disk={f"{ORM}/a.py", "odoo/db/pool.py"}
        )
        self.assertIn("odoo/db/pool.py", verdict.out_of_scope)

    def test_unchecked_when_mypy_never_looked_at_an_in_scope_file(self) -> None:
        verdict = self.evaluate(checked={f"{ORM}/a.py"})
        self.assertEqual(verdict.unchecked, [f"{ORM}/b.py"])

    def test_an_unchecked_file_is_not_counted_as_locked(self) -> None:
        self.assertEqual(self.evaluate(checked={f"{ORM}/a.py"}).locked, 1)


class TheDriftTheRatchetCannotSee(unittest.TestCase):
    """The scenario this gate exists for, pinned as a test.

    One error moves off a file that is already excepted and onto one that is
    clean and locked. The project-wide total does not move, so
    ``tooling/ratchet`` reports no drift; the lock is nonetheless gone.
    """

    def test_a_count_neutral_swap_is_green_by_count_and_red_by_lock(self) -> None:
        before = {f"{ORM}/debt.py": {"[misc]": 2}}
        after = {f"{ORM}/debt.py": {"[misc]": 1}, f"{ORM}/clean.py": {"[misc]": 1}}
        self.assertEqual(  # what the ratchet measures, and it has not moved
            sum(sum(c.values()) for c in before.values()),
            sum(sum(c.values()) for c in after.values()),
        )

        common = {
            "package": "orm",
            "checked": {f"{ORM}/debt.py", f"{ORM}/clean.py"},
            "exempt": [f"{ORM}/debt.py"],
            "budgets": {f"{ORM}/debt.py": 2},
            "on_disk": {f"{ORM}/debt.py", f"{ORM}/clean.py"},
        }
        self.assertEqual(gate.evaluate_package(errors=before, **common).failures, 0)
        verdict = gate.evaluate_package(errors=after, **common)
        self.assertEqual(verdict.regressed, [f"{ORM}/clean.py"])


class Markdown(unittest.TestCase):
    """The step summary is code here rather than a heredoc in the workflow, so it
    is testable — and this is what makes that claim true."""

    def render(self, **kwargs) -> str:
        import io

        verdict = gate.PackageVerdict("orm", locked=3, excepted=1, **kwargs)
        buffer = io.StringIO()
        gate.markdown([verdict], stream=buffer)
        return buffer.getvalue()

    def test_green_run_emits_no_empty_bold(self) -> None:
        """`**{0 or ''}**` renders as a literal `****`, not as an empty cell."""
        self.assertNotIn("****", self.render())

    def test_every_row_is_a_well_formed_table_row(self) -> None:
        for line in self.render().strip().splitlines():
            self.assertTrue(line.startswith("|") and line.endswith("|"), line)

    def test_a_failure_is_visible_in_the_table_and_the_note(self) -> None:
        out = self.render(regressed=["odoo/orm/a.py"])
        self.assertIn("**1**", out)
        self.assertIn(":x:", out)


class CommittedState(unittest.TestCase):
    """Invariants of the checked-in lists — these catch a hand-edit."""

    def test_every_package_has_both_files(self) -> None:
        for package in gate.SCOPED_PACKAGES:
            self.assertTrue(gate.exceptions_path(package).is_file(), package)
            self.assertTrue(gate.budgets_path(package).is_file(), package)

    def test_every_excepted_path_exists_and_belongs_to_its_package(self) -> None:
        for package in gate.SCOPED_PACKAGES:
            on_disk = gate.package_files(package)
            for path in gate.read_exceptions(package):
                self.assertIn(path, on_disk, f"{package}: stale entry {path}")
                self.assertEqual(gate.package_of(path), package, path)

    def test_membership_and_budgets_agree(self) -> None:
        for package in gate.SCOPED_PACKAGES:
            self.assertEqual(
                set(gate.read_exceptions(package)),
                set(gate.read_budgets(package)),
                f"{package}: exception list and budget keys diverged",
            )

    def test_budget_totals_are_the_sum_of_their_entries(self) -> None:
        for package in gate.SCOPED_PACKAGES:
            data = json.loads(gate.budgets_path(package).read_text())
            self.assertEqual(data["total"], sum(data["budgets"].values()), package)

    def test_the_lists_are_not_empty_in_every_package(self) -> None:
        """A gate whose state is all-empty would pass over anything."""
        self.assertTrue(any(gate.read_exceptions(p) for p in gate.SCOPED_PACKAGES))

    def test_scoped_packages_all_exist(self) -> None:
        for package in gate.SCOPED_PACKAGES:
            self.assertTrue((gate.REPO / "odoo" / package).is_dir(), package)


if __name__ == "__main__":
    unittest.main(verbosity=2)
