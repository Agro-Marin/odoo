import json
from pathlib import Path

import pytest
from js_patch_blind_facade import ACORN, main, measure

pytestmark = pytest.mark.skipif(
    not ACORN.is_file(), reason="acorn not installed (run `npm ci`)"
)

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
    src = _tree(tmp_path, **{"command_service.js": BUGGY})
    found = measure(src=src)
    methods = {v.method for v in found}
    assert methods == {"openMainPalette", "openPalette"}
    assert all(v.lines for v in found)


def test_passes_the_fixed_shape(tmp_path):
    src = _tree(tmp_path, **{"command_service.js": FIXED})
    assert measure(src=src) == []


def test_refuses_an_empty_tree(tmp_path):
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
    src = _tree(tmp_path, **{"command_service.js": BUGGY})
    monkeypatch.setattr("js_patch_blind_facade.WEB_SRC", src)
    assert main(["--check"]) == 1
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "openMainPalette" in out


def test_json_and_count_agree(tmp_path, monkeypatch, capsys):
    src = _tree(tmp_path, **{"command_service.js": BUGGY})
    monkeypatch.setattr("js_patch_blind_facade.WEB_SRC", src)
    assert main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert main(["--count"]) == 0
    assert int(capsys.readouterr().out.strip()) == len(payload)
