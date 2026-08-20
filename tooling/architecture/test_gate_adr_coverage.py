from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import layer_check as lc

HERE = Path(__file__).resolve().parent
ADR_DIR = lc.ROOT / "doc" / "adr"

UNRECORDED_GATES: frozenset[str] = frozenset(
    {
        # Landed with the mail work, each argued for in its own commit message
        # rather than in a record. Listed here so the omission is visible and
        # owed, which is what this list is for -- not so it stops being owed.
        "compute_context_deps.py",
        "mail_hook_keyword_check.py",
        "sql_placeholder.py",
        "translation_catalog.py",
    }
)


def gate_modules() -> list[Path]:
    found = []
    for path in sorted(HERE.glob("*.py")):
        if path.name.startswith(("test_", "_")):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(isinstance(n, ast.FunctionDef) and n.name == "main" for n in tree.body):
            found.append(path)
    return found


def declared_adr(path: Path) -> str | None:

    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "ADR" for t in node.targets
        ):
            if isinstance(node.value, ast.Constant) and isinstance(
                node.value.value, str
            ):
                return node.value.value
    return None


def _status_kind(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("- **Status:**"):
            rest = line.removeprefix("- **Status:**").split()
            return rest[0] if rest else ""
    return ""


def test_the_gate_list_is_not_empty():
    assert len(gate_modules()) > 20, (
        f"only {len(gate_modules())} gates found in {HERE} — the discovery rule "
        f"is broken, and every check in this file would pass by finding nothing."
    )


def test_every_gate_declares_an_adr():
    for path in gate_modules():
        assert declared_adr(path) is not None, (
            f"{path.name} declares no module-level ADR. A gate that fails a "
            f'build states which record argues for it — ADR = "0005" — or '
            f'ADR = "{lc.UNRECORDED}" with its name added to UNRECORDED_GATES.'
        )


def test_every_cited_record_exists_and_is_accepted():
    for path in gate_modules():
        adr = declared_adr(path)
        if adr is None or adr == lc.UNRECORDED:
            continue
        matches = list(ADR_DIR.glob(f"{adr}-*.md"))
        assert matches, (
            f"{path.name} cites ADR-{adr}, which is not in doc/adr/. If the "
            f"record moved, follow it."
        )
        kind = _status_kind(matches[0])
        assert kind == "Accepted", (
            f"{path.name} cites ADR-{adr}, whose status is {kind}. A gate "
            f"enforces a decision that has landed; cite an Accepted record, or "
            f'declare ADR = "{lc.UNRECORDED}" until this one is.'
        )


def test_the_unrecorded_gates_are_pinned_and_shrinking():
    unrecorded = {p.name for p in gate_modules() if declared_adr(p) == lc.UNRECORDED}
    new = unrecorded - UNRECORDED_GATES
    assert not new, (
        f"gate(s) with no ADR: {sorted(new)}. A boundary worth failing CI over "
        f"is worth a decision record — write one and set ADR, or add the name "
        f"to UNRECORDED_GATES with your reason for deferring."
    )
    written_up = UNRECORDED_GATES - unrecorded
    assert not written_up, (
        f"{sorted(written_up)} now name an ADR. Good — remove them from "
        f"UNRECORDED_GATES so the count cannot drift back up."
    )


def test_a_stale_pin_cannot_hide_a_deleted_gate():

    present = {p.name for p in gate_modules()}
    ghosts = UNRECORDED_GATES - present
    assert not ghosts, (
        f"{sorted(ghosts)} are pinned in UNRECORDED_GATES but are no longer "
        f"gates in this directory. Remove them."
    )
