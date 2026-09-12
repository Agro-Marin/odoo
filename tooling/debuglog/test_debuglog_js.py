import textwrap
from pathlib import Path

import pytest

from . import debuglog_js

CLEAN = textwrap.dedent(
    """
    // @ts-check
    /** @odoo-module native */

    import { Component } from "@odoo/owl";
    import { registry } from "@web/core/registry";

    export class Thing extends Component {
        setup() {
            this.registry = registry;
        }

        async load(ids) {
            const rows = await this.orm.read(ids);
            if (rows.length) {
                this.rows = rows;
            }
            return rows;
        }
    }
    """
).lstrip()

INSTRUMENTED = textwrap.dedent(
    """
    // @ts-check
    /** @odoo-module native */

    import { Component } from "@odoo/owl";
    import { makeLogger } from "@web/core/debug/debug_logger";
    import { useLifecycleLog } from "@web/core/debug/logger_hooks";
    import { registry } from "@web/core/registry";

    const log = makeLogger("web.thing");

    export class Thing extends Component {
        setup() {
            useLifecycleLog(log);
            this.registry = registry;
        }

        async load(ids) {
            log.pipeline("load", () => ({
                ids: ids.length,
                label: `thing (${ids.length})`,
            }));
            const endLoad = log.perf("load");
            const rows = await this.orm.read(ids);
            endLoad({ rows: rows.length });
            if (rows.length) {
                log.logic("has rows");
                this.rows = rows;
            }
            return rows;
        }
    }
    """
).lstrip()


def _write(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "thing.js"
    path.write_text(source)
    return path


def _messages(report):
    return [violation.message for violation in report.violations]


def test_every_documented_shape_passes_check(tmp_path):
    report = debuglog_js.scan_file(_write(tmp_path, INSTRUMENTED))
    assert _messages(report) == []
    kinds = [site.kind for site in report.sites]
    assert kinds.count("import") == 2
    assert kinds.count("declaration") == 1
    assert kinds.count("hook") == 1
    assert kinds.count("call") == 2
    assert kinds.count("perf") == 1
    assert kinds.count("perf-end") == 1


def test_strip_restores_the_clean_module(tmp_path):
    path = _write(tmp_path, INSTRUMENTED)
    report = debuglog_js.scan_file(path)
    assert debuglog_js.strip_file(path, report)
    assert path.read_text() == CLEAN
    assert _messages(debuglog_js.scan_file(path)) == []
    assert debuglog_js.scan_file(path).sites == []


def test_a_clean_module_has_no_sites_and_no_violations(tmp_path):
    report = debuglog_js.scan_file(_write(tmp_path, CLEAN))
    assert report.sites == []
    assert report.violations == []


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ('    return log.measure("x", () => work());\n', "unstrippable use"),
        ('    const stop = log.perf("x");\n    stop();\n', "unstrippable use"),
        ('    if (ok) {\n        log.logic("only");\n    }\n', "only statement"),
        (
            '    if (log.isEnabled("perf")) {\n        work();\n    }\n',
            "unstrippable use",
        ),
    ],
)
def test_check_refuses_an_unstrippable_shape(tmp_path, body, fragment):
    source = (
        'import { makeLogger } from "@web/core/debug/debug_logger";\n\n'
        'const log = makeLogger("web.thing");\n\n'
        "export function run(ok) {\n" + body + "}\n"
    )
    report = debuglog_js.scan_file(_write(tmp_path, source))
    assert any(fragment in message for message in _messages(report)), _messages(report)


def test_a_multi_line_call_with_a_template_literal_is_one_site(tmp_path):
    source = (
        'const log = makeLogger("web.thing");\n\n'
        "export function run(a) {\n"
        '    log.logic("run", () => ({\n'
        "        label: `a ) still inside ( the template`,\n"
        "        a,\n"
        "    }));\n"
        "    return a;\n"
        "}\n"
    )
    report = debuglog_js.scan_file(_write(tmp_path, source))
    calls = [site for site in report.sites if site.kind == "call"]
    assert [(site.line, site.end) for site in calls] == [(4, 7)]
    assert _messages(report) == []
