"""The round trip, pinned. This tool rewrites 207 files in place.

`stamp.py`'s whole safety argument is one sentence in its docstring: "every line
it inserts carries the `SENTINEL` trailing comment, and `--revert` removes lines
carrying that comment and nothing else, so a stamped tree returns byte-identical
to its pre-stamp state." Nothing checked it.

It holds today — measured 2026-08-25 on an isolated worktree: 207 files stamped,
reverted, `git status` clean. It is also exactly the kind of invariant a later
edit to `SETUP_RE`, `insert_import` or `resolve_labels` breaks silently, on a
tool whose failure mode is a corrupted working tree that `--revert` can no
longer undo.

The tests below work on text, not on the checkout: `apply_to_text` and
`revert_text` are the pair the invariant is about, and a temporary tree keeps the
round trip honest without a full JS corpus.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import stamp

COMPONENT = '''/** @odoo-module */
import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class ThingRenderer extends Component {
    static template = "web.Thing";
    setup() {
        this.orm = useService("orm");
    }
    onClick() {
        return 1;
    }
}
'''

TWO_CLASSES = '''/** @odoo-module */
import { Component } from "@odoo/owl";

export class Alpha extends Component {
    setup() {
        this.a = 1;
    }
}

class Beta extends Component {
    setup() {
        this.b = 2;
    }
}
'''

NO_COMPONENT = '''/** @odoo-module */
export function helper(x) {
    return x + 1;
}
'''


def _stamp(text: str, path: Path) -> tuple[str, int, list[str]]:
    labels = stamp.resolve_labels([_write(path, text)])
    return stamp.apply_to_text(text, path, labels)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("source", [COMPONENT, TWO_CLASSES], ids=["one", "two"])
def test_the_round_trip_is_byte_identical(tmp_path, source):
    path = tmp_path / "web" / "static" / "src" / "thing.js"
    stamped, _written, _over = _stamp(source, path)
    assert stamped != source, "nothing was stamped — the probe found no site"
    reverted, _removed = stamp.revert_text(stamped)
    assert reverted == source


def test_apply_and_revert_count_the_same_unit(tmp_path):
    # They did not: `apply` returned len(sites) and `revert` the sentinel lines
    # it removed, which includes the import. Over the real tree that read as
    # "stamped 217" against "removed 424" for the same 207 files, and the
    # obvious check on an exact inverse could not be made.
    path = tmp_path / "web" / "static" / "src" / "thing.js"
    stamped, written, _over = _stamp(TWO_CLASSES, path)
    _reverted, removed = stamp.revert_text(stamped)
    assert written == removed
    assert written == 3, "two setup() probes plus one import"


def test_revert_removes_only_sentinel_lines(tmp_path):
    path = tmp_path / "web" / "static" / "src" / "thing.js"
    stamped, _written, _over = _stamp(COMPONENT, path)
    # A line that merely mentions the probe module, without the sentinel, is
    # somebody's own code and must survive.
    poisoned = stamped.replace(
        "    onClick() {",
        f'    // see {stamp.PROBE_MODULE}\n    onClick() {{',
    )
    reverted, _removed = stamp.revert_text(poisoned)
    assert f"// see {stamp.PROBE_MODULE}" in reverted
    assert stamp.SENTINEL not in reverted


def test_every_written_line_carries_the_sentinel(tmp_path):
    """The property `--revert` depends on, asserted directly.

    A stamped line that lost its sentinel would be unremovable, and the only
    symptom is a tree that will not come back.
    """
    path = tmp_path / "web" / "static" / "src" / "thing.js"
    stamped, written, _over = _stamp(TWO_CLASSES, path)
    added = [
        line
        for line in stamped.splitlines()
        if line not in TWO_CLASSES.splitlines()
    ]
    assert len(added) == written
    assert all(stamp.SENTINEL in line for line in added), added


def test_a_file_with_no_component_is_untouched(tmp_path):
    path = tmp_path / "web" / "static" / "src" / "helper.js"
    stamped, written, _over = _stamp(NO_COMPONENT, path)
    assert stamped == NO_COMPONENT
    assert written == 0


def test_a_hand_instrumented_file_is_left_alone(tmp_path):
    hand = COMPONENT.replace(
        '        this.orm = useService("orm");',
        '        useRenderCounter("thing:ThingRenderer");\n'
        '        this.orm = useService("orm");',
    )
    assert stamp.is_hand_instrumented(hand)
    path = tmp_path / "web" / "static" / "src" / "thing.js"
    stamped, written, _over = _stamp(hand, path)
    assert stamped == hand
    assert written == 0


def test_stamping_twice_does_not_double_the_import(tmp_path):
    path = tmp_path / "web" / "static" / "src" / "thing.js"
    once, _w1, _o1 = _stamp(COMPONENT, path)
    # The second pass sees its own probe and refuses the file outright, which is
    # what `is_hand_instrumented` is for; either way the import must not double.
    twice, _w2, _o2 = _stamp(once, path)
    assert twice.count(stamp.PROBE_IMPORT) == 1
    reverted, _removed = stamp.revert_text(twice)
    assert reverted == COMPONENT


def test_every_over_width_line_is_reported(tmp_path):
    """An unreported over-width line is the failure mode, not the width itself.

    Prettier reflows a line past `PRINT_WIDTH`, and a reflowed call puts the
    sentinel on a different line from the statement head -- which leaves
    `--revert` deleting one line of a three-line statement. `resolve_labels`
    keeps the probe lines under; the IMPORT is 89 columns and was checked by
    nothing, in every file the tool touches.
    """
    path = tmp_path / "web" / "static" / "src" / "thing.js"
    stamped, _written, over = _stamp(COMPONENT, path)
    wide = [
        line
        for line in stamped.splitlines()
        if stamp.SENTINEL in line and len(line) > stamp.PRINT_WIDTH
    ]
    assert len(over) == len(wide), (
        f"{len(wide)} stamped line(s) exceed {stamp.PRINT_WIDTH} columns and "
        f"{len(over)} were reported: {wide}"
    )


def test_the_probe_call_itself_stays_within_the_budget(tmp_path):
    # The half `resolve_labels` controls: it drops a label to the bare class
    # name, or qualifies it back, to keep every CALL line inside the budget.
    path = tmp_path / "web" / "static" / "src" / "thing.js"
    stamped, _written, _over = _stamp(COMPONENT, path)
    for line in stamped.splitlines():
        if stamp.SENTINEL in line and "useRenderCounter(" in line:
            assert len(line) <= stamp.PRINT_WIDTH, line
