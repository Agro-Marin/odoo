from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import js_duplication as jd


def lines(text: str) -> list[tuple[int, str]]:
    out = []
    for number, raw in enumerate(text.strip("\n").split("\n"), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith(("//", "*", "/*")):
            continue
        out.append((number, " ".join(stripped.split())))
    return out


BODY = """
const classes = ["o_event"];
const color = getColor(record.colorIndex);
if (typeof color === "number") {
    classes.push(`o_calendar_color_${color}`);
}
if (record.isHatched) {
    classes.push("o_event_hatched");
}
if (record.isStriked) {
    classes.push("o_event_striked");
}
return classes;
"""

EXTRA = """
if (record.duration <= 0.25) {
    classes.push("o_event_oneliner");
}
"""


def test_identical_bodies_are_one_run_of_their_real_length():
    a = lines(BODY)
    runs = jd.maximal_runs(a, lines(BODY))
    assert len(runs) == 1, (
        f"an identical body must be reported once, not as overlapping windows; "
        f"got {len(runs)} runs"
    )
    assert runs[0].lines == len(a)


def test_a_prefix_is_reported_at_the_length_it_actually_shares():
    short = lines(BODY)
    long = lines(BODY.rstrip() + EXTRA)
    runs = jd.maximal_runs(short, long)
    assert len(runs) == 1
    shared = runs[0].lines
    assert shared < len(long), "the longer body is not entirely shared"
    assert shared >= jd.MIN_RUN


def test_a_divergence_inside_the_block_truncates_the_run():
    a = lines(BODY)
    changed = BODY.replace(
        'classes.push("o_event_hatched");', 'classes.push("o_event_shaded");'
    )
    runs = jd.maximal_runs(a, lines(changed))
    assert all(r.lines < len(a) for r in runs), (
        "a body that differs in the middle must not be reported as a whole-body "
        "duplicate"
    )


def test_runs_below_the_floor_are_not_reported():
    short = lines("\n".join(f"const a{i} = {i};" for i in range(jd.MIN_RUN - 1)))
    assert jd.maximal_runs(short, short) == [], (
        f"a {jd.MIN_RUN - 1}-line match is idiom, not duplication"
    )


def test_reindenting_does_not_hide_a_duplicate():
    a = lines(BODY)
    b = lines("\n".join("        " + ln for ln in BODY.strip("\n").split("\n")))
    runs = jd.maximal_runs(a, b)
    assert runs and runs[0].lines == len(a)


def test_renaming_does_hide_a_duplicate_and_that_is_the_documented_trade():
    a = lines(BODY)
    b = lines(BODY.replace("classes", "cls"))
    assert jd.maximal_runs(a, b) == []


def test_comments_and_blank_lines_do_not_break_a_run():
    a = lines(BODY)
    commented = BODY.replace(
        "if (record.isHatched) {", "// decorations\n\nif (record.isHatched) {"
    )
    runs = jd.maximal_runs(a, lines(commented))
    assert runs and runs[0].lines == len(a)


def test_the_gate_measures_a_real_tree_and_reports_a_number():
    runs = jd.collect()
    assert runs, "no duplication found at all — the scan is not reaching the tree"
    assert jd.total(runs) == sum(r.lines for r in runs)
    for run in runs:
        assert run.lines >= jd.MIN_RUN
        assert run.left != run.right, "a file must not be compared with itself"


def test_candidate_pairs_lose_nothing_the_full_comparison_would_find():
    files = jd.js_files(jd.addon_src())[:60]
    lines_by_file = {p: jd.significant(p) for p in files}
    pairs = jd.candidate_pairs(files, lines_by_file)
    for x in range(len(files)):
        for y in range(x + 1, len(files)):
            a, b = sorted((files[x], files[y]))
            if (a, b) in pairs:
                continue
            assert not jd.maximal_runs(lines_by_file[a], lines_by_file[b]), (
                f"{a.name} / {b.name} were pruned but do share a run"
            )
