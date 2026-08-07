"""Tests for the doc-link cleanup ranker.

241 lines with no tests. It is not a gate — it steers attention — but the two
ways it can be wrong both cost someone an afternoon: ranking work that is
already done, and hiding work that is not. Both were real. It used to rank the
COMMITTED baseline, which on one measurement had drifted both ways (72 of 478
entries already fixed, 81 live violations absent from it), so it sent you at
finished work and concealed the rest. It now scans live by default, and
``--from-baseline`` is the opt-in.
"""

import json
import sys

import doc_link_next_target as ranker  # sys.path set by conftest.py
import pytest


def _baseline(*pairs):
    return {"violations": [{"source_file": sf, "raw_path": rp} for sf, rp in pairs]}


class TestEaseHeuristic:
    @pytest.mark.parametrize(
        ("source", "target", "expected"),
        [
            ("addons/web/machine_doc_v1/A.md", "B.md", 1.0),  # same directory
            ("addons/web/machine_doc_v1/A.md", "doc/B.md", 0.7),  # in-repo move
            ("a/b/C.md", "config/x.md", 0.3),  # lives in another repo
            ("a/b/C.md", "/home/someone/x.md", 0.3),  # absolute, machine-local
            ("a/b/C.md", "x/thoughts/y.md", 0.2),  # probably never written
        ],
    )
    def test_scores(self, source, target, expected):
        assert ranker._ease_for_ref(source, target) == pytest.approx(expected)

    def test_a_sibling_tree_reference_scores_above_a_cross_tree_one(self):
        sibling = ranker._ease_for_ref("addons/web/machine_doc_v1/A.md", "web/x.md")
        cross = ranker._ease_for_ref("addons/web/machine_doc_v1/A.md", "odoo/x.md")
        assert sibling > cross

    def test_an_anchor_does_not_change_the_score(self):
        assert ranker._ease_for_ref("a/B.md", "c/d.md#x") == ranker._ease_for_ref(
            "a/B.md", "c/d.md"
        )


class TestScoring:
    def test_one_entry_per_source_file(self):
        scores = ranker.score_files(
            _baseline(("a.md", "x.md"), ("a.md", "y.md"), ("b.md", "z.md"))
        )
        assert {s.source_file for s in scores} == {"a.md", "b.md"}
        assert next(s for s in scores if s.source_file == "a.md").total_refs == 2

    def test_score_is_count_times_average_ease(self):
        # Deliberately mixed eases, so a scorer that returned the raw count
        # would still pass a same-ease case and hide the weighting entirely.
        score = ranker.score_files(
            _baseline(
                ("a/b.md", "c.md"),  # same directory -> 1.0
                ("a/b.md", "config/d.md"),  # another repo -> 0.3
            )
        )[0]
        assert score.total_refs == 2
        assert score.avg_ease == pytest.approx(0.65)
        assert score.score == pytest.approx(1.3)
        assert score.score != score.total_refs

    def test_two_files_with_equal_counts_are_ordered_by_ease(self):
        scores = {
            s.source_file: s.score
            for s in ranker.score_files(
                _baseline(
                    ("easy.md", "a.md"),
                    ("easy.md", "b.md"),
                    ("hard.md", "x/thoughts/a.md"),
                    ("hard.md", "x/thoughts/b.md"),
                )
            )
        }
        assert scores["easy.md"] > scores["hard.md"]

    def test_many_easy_refs_outrank_few_hard_ones(self):
        # The whole point of the ranking: fix a cluster, not a puzzle.
        scores = ranker.score_files(
            _baseline(
                *[("easy.md", f"sib{i}.md") for i in range(5)],
                ("hard.md", "x/thoughts/deep.md"),
            )
        )
        ordered = sorted(scores, key=lambda s: s.score, reverse=True)
        assert ordered[0].source_file == "easy.md"

    def test_samples_are_deduplicated_and_capped(self):
        score = ranker.score_files(
            _baseline(*[("a.md", "dup.md")] * 4, ("a.md", "b.md"), ("a.md", "c.md"))
        )[0]
        assert len(score.sample_paths) <= 3
        assert len(set(score.sample_paths)) == len(score.sample_paths)

    def test_an_empty_baseline_ranks_nothing(self):
        assert ranker.score_files({"violations": []}) == []


class TestAuthoritativeScope:
    @pytest.mark.parametrize(
        "source",
        [
            "addons/web/machine_doc_v1/A.md",
            "addons/mail/machine_doc_v1/A.md",  # NOT just web's
            "odoo/addons/base/machine_doc_v1/A.md",
            ".github/workflows/x.yml",
            "CLAUDE.md",
            "doc/adr/0001-x.md",
            "tooling/hoot/README.md",
        ],
    )
    def test_authoritative_surfaces(self, source):
        score = ranker.score_files(_baseline((source, "gone.md")))[0]
        assert score.is_authoritative, source

    def test_an_ordinary_doc_is_not_authoritative(self):
        score = ranker.score_files(
            _baseline(("addons/web/static/src/NOTES.md", "x.md"))
        )[0]
        assert not score.is_authoritative


class TestLiveByDefault:
    def test_live_scan_shares_the_gate_s_shape(self):
        # Same keys the baseline uses, so score_files takes either source.
        live = ranker._live_violations()
        assert set(live) == {"violations"}
        for entry in live["violations"]:
            assert set(entry) == {"source_file", "raw_path"}

    def test_live_scan_agrees_with_the_gate(self):
        import doc_link_gate as gate

        live = {
            (v["source_file"], v["raw_path"])
            for v in ranker._live_violations()["violations"]
        }
        assert live == {(v.source_file, v.raw_path) for v in gate.scan()}

    def _sources(self, tmp_path, monkeypatch):
        """A live scan and a committed baseline that name different files."""
        baseline = tmp_path / "baseline.json"
        baseline.write_text(
            json.dumps(_baseline(("STALE_BASELINE.md", "gone.md"))), encoding="utf-8"
        )
        monkeypatch.setattr(
            ranker, "_live_violations", lambda: _baseline(("LIVE_TREE.md", "gone.md"))
        )
        return baseline

    def test_default_run_ranks_the_live_tree(self, tmp_path, monkeypatch, capsys):
        # THE regression this tool was rewritten for: ranking the committed
        # baseline answers "what was broken when someone last ran
        # --update-baseline", which is not the question anyone is asking.
        baseline = self._sources(tmp_path, monkeypatch)
        monkeypatch.setattr(sys, "argv", ["p", "--baseline", str(baseline)])
        assert ranker._main() == 0
        out = capsys.readouterr().out
        assert "LIVE_TREE.md" in out
        assert "STALE_BASELINE.md" not in out

    def test_from_baseline_opts_back_in(self, tmp_path, monkeypatch, capsys):
        baseline = self._sources(tmp_path, monkeypatch)
        monkeypatch.setattr(
            sys, "argv", ["p", "--from-baseline", "--baseline", str(baseline)]
        )
        assert ranker._main() == 0
        out = capsys.readouterr().out
        assert "STALE_BASELINE.md" in out
        assert "LIVE_TREE.md" not in out

    def test_from_baseline_without_a_baseline_is_a_usage_error(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            sys,
            "argv",
            ["p", "--from-baseline", "--baseline", str(tmp_path / "none.json")],
        )
        assert ranker._main() == 2

    def test_empty_result_is_reported_as_clean_not_as_a_missing_baseline(self, capsys):
        # The default source is the live tree, so "nothing to rank" is the good
        # outcome and must not read as a suspected empty baseline.
        ranker._print_table([], 10)
        assert "every .md reference in scope resolves" in capsys.readouterr().out

    def test_empty_baseline_still_says_baseline(self, capsys):
        ranker._print_table([], 10, from_baseline=True)
        assert "baseline is empty" in capsys.readouterr().out
