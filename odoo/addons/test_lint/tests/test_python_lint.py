import tomllib
from pathlib import Path

import odoo

from . import _py_scan, _rules
from .lint_case import LintCase


class TestPythonLint(LintCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _py_scan.findings()

    def test_every_rule_is_held_at_its_floor(self):
        """One subTest per rule, floors read from tooling/ratchet/baselines/.

        There used to be twelve one-line methods and a `FLOORS` dict carrying a
        hundred and ninety lines of comment around twelve integers. The integers
        are baselines now; the advice is on the `Rule`.
        """
        for rule in _rules.RULES:
            with self.subTest(rule=rule.name):
                self.assert_ratchet(
                    sorted(
                        _py_scan.findings().get(rule.name, []),
                        key=lambda finding: finding.sort_key,
                    ),
                    rule.gate,
                    f"{rule.name} finding(s)",
                    f"{rule.advice}.",
                )

    def test_no_source_in_the_corpus_is_unreadable(self):
        """A file the scan cannot parse or tokenise is a hole in every rule.

        It used to be swallowed: `scan_one` caught the error and returned no
        findings, and `comment_lines` returned an empty map, which disarms every
        `# noqa` in the file and makes `noqa-rationale` report nothing. Both read
        exactly like a clean file.
        """
        broken = _py_scan.findings().get("unreadable-source", [])
        self.assertFalse(
            broken,
            f"{len(broken)} file(s) in the corpus could not be read, so every "
            f"other rule skipped them in silence:\n  "
            + "\n  ".join(str(finding) for finding in broken),
        )

    def test_every_rule_reaches_the_scan(self):
        """The registry is the only definition; nothing may name a rule outside it."""
        self.assertEqual(
            sorted(_py_scan.findings().keys() - _rules.BY_NAME.keys()),
            [],
            "these rules produce findings but are not declared in _rules.RULES",
        )
        self.assertEqual(
            sorted(_rules.EMITTED - _rules.BY_NAME.keys()),
            [],
            "these rules are emitted by a checker but not declared",
        )
        self.assertEqual(
            sorted(_rules.BY_NAME.keys() - (_rules.EMITTED | _rules.CROSS_UNIT_RULES)),
            [],
            "these rules are declared but nothing can ever emit them",
        )

    def test_every_short_code_is_declared_external_to_ruff(self):
        ruff_toml = Path(odoo.__path__[0]).parent / "ruff.toml"
        declared = set(tomllib.loads(ruff_toml.read_text())["lint"]["external"])
        codes = {rule.code for rule in _rules.RULES if rule.code}
        self.assertEqual(
            sorted(codes - declared),
            [],
            f"these checker codes are not in {ruff_toml.name}'s lint.external, "
            "so ruff reports RUF102 on any noqa that uses them",
        )

    def test_the_scan_leaves_no_child_process_behind(self):
        import psutil

        _py_scan.findings()
        _py_scan._run_parallel([], 2)
        self.assertEqual(
            [f"{child.pid} {child.name()}" for child in psutil.Process().children()],
            [],
            "a worker pool must reap its own helpers, or every test class "
            "after this one waits ten seconds for them",
        )

    def test_the_parallel_scan_agrees_with_the_serial_one(self):
        sample = [
            (source.path, source.in_module)
            for source in _py_scan.corpus()
            if source.path.endswith(".py")
        ][:400]
        self.assertTrue(sample, "no files to compare the two scans on")

        serial_rows, serial_units = _py_scan.scan_many(sample)
        parallel_rows, parallel_units = _py_scan._run_parallel(sample, 4)
        self.assertEqual(sorted(parallel_rows), sorted(serial_rows))
        self.assertEqual(
            sorted(path for path, _infos in parallel_units),
            sorted(path for path, _infos in serial_units),
        )

    def test_the_corpus_is_not_empty(self):
        corpus = _py_scan.corpus()
        self.assertGreater(len(corpus), 5000, "the corpus scan reached almost nothing")
        self.assertTrue(
            any(not source.in_module for source in corpus),
            "the framework (odoo/orm, odoo/tools, ...) is missing from the "
            "corpus again -- it is where hand-built SQL actually lives",
        )
        self.assertFalse(
            [source for source in corpus if "/_vendor/" in source.path],
            "vendored third-party code is being linted; nobody here may fix a "
            "finding in it, and the next vendoring would revert the fix anyway",
        )

    def test_the_translated_column_scan_reaches_the_models(self):
        """`unique-over-translated-column` is silent on a clean tree.

        Without this, a scan that reached no model classes would report exactly
        what a scan that found no defects reports.
        """
        models, rules = _py_scan.translated_unique_scale()
        self.assertGreater(models, 1000, "the scan reached almost no models")
        self.assertGreater(rules, 100, "the scan found almost no constraints")
