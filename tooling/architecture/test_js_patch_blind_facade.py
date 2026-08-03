"""Tests for the patch-blind facade gate.

Stdlib + pytest only, matching the rest of this directory. Every case builds a
synthetic ``static/src`` so the assertions do not move when the real tree does.

The load-bearing test is ``test_detects_the_real_bug_shape``: it reproduces
``command_service.js`` as it stood before 2026-08-03, which is the shape that
let Ctrl+K bypass ``enterprise/knowledge``'s portal palette block. A gate that
only proves it stays green on a fixed tree proves nothing.
"""

import json
from pathlib import Path

import pytest
from js_patch_blind_facade import ACORN, main, measure

pytestmark = pytest.mark.skipif(
    not ACORN.is_file(), reason="acorn not installed (run `npm ci`)"
)

# The pre-fix shape: the hotkey registration captures the closure identifier,
# while the same name is published on the returned facade.
BUGGY = """
import { registry } from "@web/core/registry";
export const commandService = {
    start(env, { hotkey }) {
        function openMainPalette(config) { return openPalette(config); }
        function openPalette(config) { return config; }
        hotkey.add("control+k", () => openMainPalette());
        return { openMainPalette, openPalette };
    },
};
registry.category("services").add("command", commandService);
"""

# The fix: the facade is named, and internal callers go through it, so the
# lookup happens at call time and a patch is visible to everyone.
FIXED = """
import { registry } from "@web/core/registry";
export const commandService = {
    start(env, { hotkey }) {
        function openMainPalette(config) { return commandServiceApi.openPalette(config); }
        function openPalette(config) { return config; }
        const commandServiceApi = { openMainPalette, openPalette };
        hotkey.add("control+k", () => commandServiceApi.openMainPalette());
        return commandServiceApi;
    },
};
registry.category("services").add("command", commandService);
"""


def _tree(tmp_path: Path, **files: str) -> Path:
    src = tmp_path / "static" / "src"
    for name, body in files.items():
        target = src / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return src


def test_detects_the_real_bug_shape(tmp_path):
    """The exact shape that shipped the Ctrl+K bypass must be caught."""
    src = _tree(tmp_path, **{"command_service.js": BUGGY})
    found = measure(src=src)
    methods = {v.method for v in found}
    assert methods == {"openMainPalette", "openPalette"}
    # and it must point at the offending lines, not just name the file
    assert all(v.lines for v in found)


def test_passes_the_fixed_shape(tmp_path):
    src = _tree(tmp_path, **{"command_service.js": FIXED})
    assert measure(src=src) == []


def test_refuses_an_empty_tree(tmp_path):
    """A gate that analyses nothing must fail, not report zero violations."""
    src = tmp_path / "static" / "src"
    src.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="no service definitions"):
        measure(src=src)


def test_refuses_a_tree_with_js_but_no_services(tmp_path):
    src = _tree(tmp_path, **{"helper.js": "export const x = 1;\n"})
    with pytest.raises(RuntimeError, match="no service definitions"):
        measure(src=src)


def test_refuses_an_absent_tree(tmp_path):
    with pytest.raises(RuntimeError, match="source tree not found"):
        measure(src=tmp_path / "nope")


def test_ignores_calls_to_unpublished_helpers(tmp_path):
    """Calling a private helper is normal and must not be reported."""
    body = """
    import { registry } from "@web/core/registry";
    export const svc = {
        start() {
            function helper() { return 1; }
            function published() { return helper(); }
            return { published };
        },
    };
    registry.category("services").add("svc", svc);
    """
    src = _tree(tmp_path, **{"svc_service.js": body})
    assert measure(src=src) == []


def test_detects_facade_bound_to_a_const(tmp_path):
    """The facade may be returned via an identifier; still analysed."""
    body = """
    import { registry } from "@web/core/registry";
    export const svc = {
        start() {
            function reload() { return 1; }
            function boot() { return reload(); }
            const api = { reload, boot };
            return api;
        },
    };
    registry.category("services").add("svc", svc);
    """
    src = _tree(tmp_path, **{"svc_service.js": body})
    assert {v.method for v in measure(src=src)} == {"reload"}


def test_method_shorthand_on_the_facade_is_covered(tmp_path):
    """A shorthand method is published under its own name."""
    body = """
    import { registry } from "@web/core/registry";
    export const svc = {
        start() {
            function tick() { return 1; }
            return {
                tick,
                run() { return tick(); },
            };
        },
    };
    registry.category("services").add("svc", svc);
    """
    src = _tree(tmp_path, **{"svc_service.js": body})
    assert {v.method for v in measure(src=src)} == {"tick"}


def test_parse_error_is_raised_not_swallowed(tmp_path):
    src = _tree(
        tmp_path,
        **{"broken_service.js": 'registry.category("services").add("x", { start( {'},
    )
    with pytest.raises(RuntimeError, match="parse failed"):
        measure(src=src)


def test_check_flag_exits_nonzero_on_drift(tmp_path, monkeypatch, capsys):
    """`--check` is the only part CI reads; report mode must stay exit 0."""
    src = _tree(tmp_path, **{"command_service.js": BUGGY})
    monkeypatch.setattr("js_patch_blind_facade.WEB_SRC", src)
    assert main(["--check"]) == 1
    assert main([]) == 0  # report mode does not gate
    out = capsys.readouterr().out
    assert "openMainPalette" in out


def test_json_and_count_agree(tmp_path, monkeypatch, capsys):
    src = _tree(tmp_path, **{"command_service.js": BUGGY})
    monkeypatch.setattr("js_patch_blind_facade.WEB_SRC", src)
    assert main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert main(["--count"]) == 0
    assert int(capsys.readouterr().out.strip()) == len(payload)
