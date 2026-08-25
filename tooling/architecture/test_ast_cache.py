"""The cache hands the same tree to several readers, so its contract is safety.

Two properties matter more than the speedup. First, retaining is OFF unless a
gate asks for it, because it is a measured loss for every gate that walks the
corpus once. Second, a cached tree is SHARED, so nothing may mutate one -- the
last test here pins that across the whole gate directory rather than trusting
the four call sites that exist today.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _ast_cache

HERE = Path(__file__).resolve().parent
SAMPLE = HERE / "_ast_cache.py"


@pytest.fixture(autouse=True)
def _reset():
    _ast_cache.clear()
    _ast_cache._STATE["enabled"] = False
    yield
    _ast_cache.clear()
    _ast_cache._STATE["enabled"] = False


def test_disabled_by_default_retains_nothing():
    first = _ast_cache.parse_file(SAMPLE)
    second = _ast_cache.parse_file(SAMPLE)
    assert first is not second, (
        "retaining must be opt-in: it costs the single-walk gates"
    )
    assert not _ast_cache._TREES


def test_enable_reuses_one_tree():
    _ast_cache.enable()
    assert _ast_cache.parse_file(SAMPLE) is _ast_cache.parse_file(SAMPLE)


def test_the_tree_is_what_a_direct_parse_would_have_given():
    direct = ast.parse(SAMPLE.read_text(encoding="utf-8"))
    _ast_cache.enable()
    assert ast.dump(_ast_cache.parse_file(SAMPLE)) == ast.dump(direct)


@pytest.fixture
def bad_bytes(tmp_path):
    """A source file that is valid Python but not valid UTF-8.

    The ONLY input on which `errors="strict"` and `errors="ignore"` disagree,
    and therefore the only one that can distinguish the two modes at all. The
    corpus holds none -- 0 of 10047 `.py` files under `odoo/` and `addons/`
    fail a strict decode -- which is why keying the cache per mode bought
    nothing and cost a second copy of every file.
    """
    path = tmp_path / "mojibake.py"
    path.write_bytes(b'X = "caf\xe9"\n')  # latin-1 e-acute, invalid UTF-8
    return path


def test_a_lenient_reader_reuses_the_strict_tree():
    # A file that decodes strictly decodes IDENTICALLY when errors are ignored,
    # so the two modes want the same tree and holding two is pure waste.
    _ast_cache.enable()
    strict = _ast_cache.parse_file(SAMPLE)
    assert _ast_cache.parse_file(SAMPLE, errors="ignore") is strict
    assert len(_ast_cache._TREES) == 1


def test_a_strict_decode_failure_is_never_served_to_a_lenient_reader(bad_bytes):
    # The case the per-mode key was defending, and the one that survives: a
    # lenient caller catches SyntaxError only, so handing it the strict read's
    # UnicodeDecodeError would surface as an uncaught error inside the gate.
    _ast_cache.enable()
    with pytest.raises(UnicodeDecodeError):
        _ast_cache.parse_file(bad_bytes)
    tree = _ast_cache.parse_file(bad_bytes, errors="ignore")
    assert isinstance(tree, ast.Module)


def test_a_lenient_tree_is_never_served_to_a_strict_reader(bad_bytes):
    # The other direction, which is NOT symmetric: the lenient tree was parsed
    # from silently-dropped bytes, and a caller that asked to be told about them
    # must still be told.
    _ast_cache.enable()
    assert isinstance(_ast_cache.parse_file(bad_bytes, errors="ignore"), ast.Module)
    with pytest.raises(UnicodeDecodeError):
        _ast_cache.parse_file(bad_bytes)


def test_two_lenient_modes_never_share(bad_bytes):
    # `ignore` DROPS the undecodable byte, `replace` substitutes U+FFFD, so the
    # two produce different trees. The first version of the path-keyed cache
    # asked only "is the caller strict?" and served `replace` the `ignore` tree:
    # `X = "caf"` where `X = "caf\ufffd"` was correct, silently, forever.
    _ast_cache.enable()
    dropped = _ast_cache.parse_file(bad_bytes, errors="ignore")
    substituted = _ast_cache.parse_file(bad_bytes, errors="replace")
    assert dropped is not substituted
    assert dropped.body[0].value.value == "caf"
    assert substituted.body[0].value.value == "caf\ufffd"


def test_a_lenient_entry_is_not_evicted_by_another_lenient_mode(bad_bytes):
    # Storing the second mode would make the pair thrash: each call evicts the
    # other's entry and neither ever hits.
    _ast_cache.enable()
    first = _ast_cache.parse_file(bad_bytes, errors="ignore")
    _ast_cache.parse_file(bad_bytes, errors="replace")
    assert _ast_cache.parse_file(bad_bytes, errors="ignore") is first


def test_a_strict_read_upgrades_the_slot_a_lenient_read_opened():
    # Order must not decide how many copies are held. A lenient read first, then
    # a strict one, must leave ONE entry that answers both -- otherwise the
    # saving depends on which gate happens to run first.
    _ast_cache.enable()
    _ast_cache.parse_file(SAMPLE, errors="ignore")
    strict = _ast_cache.parse_file(SAMPLE)
    assert _ast_cache.parse_file(SAMPLE, errors="ignore") is strict
    assert len(_ast_cache._TREES) == 1


def test_a_syntax_error_is_reraised_every_time(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("def (:\n", encoding="utf-8")
    _ast_cache.enable()
    for _ in range(3):
        with pytest.raises(SyntaxError):
            _ast_cache.parse_file(bad)


def test_a_reraised_failure_does_not_accumulate_traceback(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("def (:\n", encoding="utf-8")
    _ast_cache.enable()
    depths = []
    for _ in range(3):
        try:
            _ast_cache.parse_file(bad)
        except SyntaxError as exc:
            depth = 0
            tb = exc.__traceback__
            while tb is not None:
                depth += 1
                tb = tb.tb_next
            depths.append(depth)
    assert len(set(depths)) == 1, f"traceback grew across re-raises: {depths}"


def test_a_missing_file_raises_oserror():
    _ast_cache.enable()
    with pytest.raises(OSError):
        _ast_cache.parse_file(HERE / "does_not_exist.py")


def test_clear_drops_the_cache():
    _ast_cache.enable()
    first = _ast_cache.parse_file(SAMPLE)
    _ast_cache.clear()
    assert _ast_cache.parse_file(SAMPLE) is not first


def test_doc_restated_counts_is_still_the_caller_that_enables_it():
    # The 145s -> 95s only happens if this call survives; a refactor that drops
    # it costs 50s silently, because every output stays identical.
    source = (HERE / "doc_restated_counts.py").read_text(encoding="utf-8")
    assert "_ast_cache.enable()" in source

    enablers = [
        path.name
        for path in sorted(HERE.glob("*.py"))
        if not path.name.startswith("test_")
        and "_ast_cache.enable()" in path.read_text(encoding="utf-8")
    ]
    assert enablers == ["doc_restated_counts.py"], (
        f"a second gate turned retaining on: {enablers}. Retaining is a loss "
        f"unless the gate walks the same files twice -- measure before adding one."
    )


def _rewrites_a_tree(path: Path) -> list[str]:
    return [
        f"{path.name}:{node.lineno}"
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Attribute)
        and node.attr in {"NodeTransformer", "fix_missing_locations"}
    ]


def test_no_gate_mutates_a_syntax_tree():
    # The cache hands one tree to every reader, so a mutating consumer would
    # corrupt each later one. Nothing does today; this keeps it that way.
    offenders = []
    for path in sorted(HERE.glob("*.py")):
        if path.name.startswith("test_"):
            continue
        offenders.extend(_rewrites_a_tree(path))
    assert not offenders, f"these rewrite syntax trees the cache shares: {offenders}"
