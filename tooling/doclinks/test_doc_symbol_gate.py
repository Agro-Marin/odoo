"""Tests for the documented-symbol gate.

Two failure modes are worth more than the rest. A gate anchored on the wrong
root, or with patterns that match nothing, scans zero claims and exits 0 while
the tree rots — the same silent pass ``test_doc_link_gate.py`` was written
against. And an allowlist entry that stops being true turns into a permanent
excuse. Both are pinned below.
"""

from pathlib import Path

import doc_symbol_gate as gate
import pytest
from _repo_root import find_odoo_root

#: The document as it stood before the ``derived`` entries were corrected. Kept
#: inline rather than read from git so the test does not depend on history
#: staying reachable.
PRE_FIX_EXCERPT = """
| Concept | OWL-native spelling |
|---------|---------------------|
| Process-scoped effect | `effect(cb, deps)` (from `@web/core/utils/reactive`) |
| Computed / derived value (free-standing) | `derived(() => …)` (from \
`@web/core/utils/reactive`) — read via `.value` |

```
├─ Stateful UI behavior with computed logic?
│  └─ Derivation spans multiple sources or wants to be passed around?
│     └─ derived(() => …) from @web/core/utils/reactive — read via
│        ``.value``.
```
"""


class TestRootResolution:
    def test_repo_root_is_the_checkout_root(self):
        assert (gate.REPO_ROOT / "odoo-bin").is_file()

    def test_this_file_lives_under_the_resolved_root(self):
        assert Path(__file__).resolve().is_relative_to(gate.REPO_ROOT)

    def test_missing_marker_raises_instead_of_guessing_a_root(self):
        with pytest.raises(SystemExit) as excinfo:
            find_odoo_root(Path("/nonexistent/deep/path"), tool="probe")
        assert "odoo-bin" in str(excinfo.value)

    def test_scope_never_leaves_this_checkout(self):
        for glob in gate.DEFAULT_SCAN_GLOBS:
            assert not glob.startswith(("/", "..")), glob
        for path in gate._glob_files():
            assert path.is_relative_to(gate.REPO_ROOT), path


class TestScanCoverage:
    def test_globs_match_a_nonzero_number_of_documents(self):
        """An empty match set is the silent-no-op signature."""
        assert gate._glob_files(), (
            "doc_symbol_gate matched zero documents — it would report success "
            "regardless of how many documented symbols are missing"
        )

    def test_an_empty_document_set_refuses_to_pass(self, monkeypatch):
        monkeypatch.setattr(gate, "_glob_files", lambda *a, **k: [])
        assert gate.main([]) == 2

    def test_web_s_machine_doc_is_in_scope(self):
        scanned = {p.relative_to(gate.REPO_ROOT).as_posix() for p in gate._glob_files()}
        assert "addons/web/machine_doc_v1/STATE_MANAGEMENT.md" in scanned

    def test_more_than_one_addon_s_machine_doc_is_covered(self):
        addons = {
            p.relative_to(gate.REPO_ROOT).parts[1]
            for p in gate._glob_files()
            if "machine_doc_v1" in p.parts
        }
        assert len(addons) > 1, f"only {addons} covered — the glob is too narrow"


class TestSpecifierResolution:
    def test_a_web_module_resolves_through_the_addon_layout(self):
        resolved = gate.resolve_specifier("@web/core/utils/reactive")
        assert resolved is not None
        assert resolved.name == "reactive.js"

    def test_a_vendored_specifier_is_skipped_not_failed(self):
        assert gate.resolve_specifier("@odoo/owl") is None

    def test_an_absent_addon_is_skipped_not_failed(self):
        assert gate.resolve_specifier("@no_such_addon/thing") is None


class TestExportExtraction:
    def test_declared_exports_are_found(self):
        module = gate.resolve_specifier("@web/core/utils/reactive")
        names = gate.exported_names(module)
        assert {"SignalStore", "effect", "disposableEffect"} <= names

    def test_the_symbol_this_gate_was_written_for_is_still_absent(self):
        module = gate.resolve_specifier("@web/core/utils/reactive")
        assert "derived" not in gate.exported_names(module), (
            "A free-standing `derived` cannot track in OWL — subscriptions are "
            "keyed on the proxy a read travels through. If this is being added, "
            "read STATE_MANAGEMENT.md first."
        )

    def test_a_star_reexport_makes_the_set_undecidable(self, tmp_path):
        module = tmp_path / "m.js"
        module.write_text("export * from './other';\n")
        assert gate.exported_names(module) is None


class TestDetection:
    def test_the_pre_fix_document_is_caught(self, tmp_path, monkeypatch):
        """THE regression: this is the defect the gate exists for."""
        doc = gate.REPO_ROOT / "addons" / "web" / "machine_doc_v1" / "_probe_pre_fix.md"
        doc.write_text(PRE_FIX_EXCERPT)
        try:
            violations = gate.scan([doc])
        finally:
            doc.unlink()
        assert [v.symbol for v in violations] == ["derived"], violations

    def test_the_live_tree_is_clean(self):
        violations = gate.scan()
        assert not violations, "\n".join(v.render() for v in violations)

    def test_a_symbol_that_does_exist_is_not_flagged(self):
        doc = gate.REPO_ROOT / "addons" / "web" / "machine_doc_v1" / "_probe_ok.md"
        doc.write_text("`effect(cb, deps)` (from `@web/core/utils/reactive`)\n")
        try:
            assert gate.scan([doc]) == []
        finally:
            doc.unlink()


class TestDeliberateAbsences:
    def test_every_allowlisted_symbol_is_genuinely_still_absent(self):
        """An excuse that stopped being true is a permanent hole."""
        for (document, symbol), reason in gate.DELIBERATE_ABSENCES.items():
            assert reason.strip(), f"{document}:{symbol} has no rationale"
            path = gate.REPO_ROOT / document
            assert path.is_file(), f"{document} no longer exists — drop the entry"
            text = path.read_text(encoding="utf8")
            assert symbol in text, (
                f"{document} no longer mentions `{symbol}` — drop the entry"
            )

    def test_an_allowlisted_document_is_not_blanket_excused(self):
        """The key is (document, symbol), so a second bad symbol still fails."""
        document = "addons/web/machine_doc_v1/STATE_MANAGEMENT.md"
        assert (document, "Reactive") in gate.DELIBERATE_ABSENCES
        doc = gate.REPO_ROOT / "addons" / "web" / "machine_doc_v1" / "_probe_blanket.md"
        doc.write_text(
            "`Reactive(x)` (from `@web/core/utils/reactive`)\n"
            "`notAThing(x)` (from `@web/core/utils/reactive`)\n"
        )
        try:
            violations = gate.scan([doc])
        finally:
            doc.unlink()
        # A different document, so even `Reactive` is not excused here.
        assert {v.symbol for v in violations} == {"Reactive", "notAThing"}
