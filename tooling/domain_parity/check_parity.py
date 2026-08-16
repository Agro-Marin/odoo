#!/usr/bin/env python


from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

REPO_ROOT = find_odoo_root(pathlib.Path(__file__).resolve(), tool="check_parity")
TEST_FILE = REPO_ROOT / "addons/web/static/tests/core/domain_server_parity.test.js"

UNACCENT_REQUIRED = True

CREATION_NULLS = {
    0: ("partner_latitude",),
}


def extract_arrays(test_file: pathlib.Path) -> tuple[list[dict], list[list]]:

    script = f"""
        const fs = require("node:fs");
        const source = fs.readFileSync({json.dumps(str(test_file))}, "utf8");
        const grab = (name) => {{
            const start = source.indexOf(`const ${{name}} = [`);
            if (start === -1) {{
                throw new Error(`${{name}} not found in the test file`);
            }}
            const open = source.indexOf("[", start);
            let depth = 0;
            for (let i = open; i < source.length; i++) {{
                if (source[i] === "[") depth++;
                else if (source[i] === "]" && --depth === 0) {{
                    return source.slice(open, i + 1);
                }}
            }}
            throw new Error(`unterminated ${{name}}`);
        }};
        const RECORDS = eval(grab("RECORDS"));
        const CASES = eval(grab("CASES"));
        process.stdout.write(JSON.stringify({{ RECORDS, CASES }}));
    """
    out = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=True
    )
    payload = json.loads(out.stdout)
    return payload["RECORDS"], payload["CASES"]


def to_server_value(value):
    return value


def server_verdicts(env, records: list[dict], cases: list[list]) -> dict:
    partner_model = env["res.partner"]
    fields = [name for name in records[0] if name != "__id"]

    cr = env.cr
    cr.execute("SAVEPOINT domain_parity")
    try:
        partners = partner_model.create(
            [
                {
                    name: (record[name] if record[name] is not None else False)
                    for name in fields
                    if name not in CREATION_NULLS.get(index, ())
                }
                for index, record in enumerate(records)
            ]
        )
        stored = partners.read(fields)
        shape_drift = [
            f"{expected.get('name')}.{name}: "
            f"corpus={expected[name]!r} database={actual[name]!r}"
            for expected, actual in zip(records, stored, strict=True)
            for name in fields
            if expected[name] != actual[name]
        ]

        verdicts = {}
        rejected = 0
        for field, operator, value, _expected in cases:
            key = f"{field}|{operator}|{json.dumps(value)}"
            try:
                matched = partners.filtered_domain(
                    [(field, operator, to_server_value(value))]
                )
            except Exception:
                rejected += 1
                continue
            verdicts[key] = "".join(
                "1" if partner in matched else "0" for partner in partners
            )
        return {
            "verdicts": verdicts,
            "rejected": rejected,
            "shape_drift": shape_drift,
        }
    finally:
        cr.execute("ROLLBACK TO SAVEPOINT domain_parity")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--config", default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument(
        "--test-file",
        type=pathlib.Path,
        default=TEST_FILE,
        help="the parity test to verify (defaults to the committed one)",
    )
    args = parser.parse_args()

    sys.path.insert(0, str(REPO_ROOT))
    import odoo
    from odoo import SUPERUSER_ID, api

    odoo.tools.config.parse_config(
        ["-c", args.config] if args.config else ["--no-http"]
    )
    registry = odoo.modules.registry.Registry(args.database)

    records, cases = extract_arrays(args.test_file)

    with registry.cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})
        if UNACCENT_REQUIRED and not registry.has_unaccent:
            print(
                "SKIP: this database has no unaccent extension; the corpus was "
                "generated with it and every ilike case would look divergent. "
                "Nothing was verified — re-run against a database with "
                "unaccent, or the parity snapshot stays unchecked.",
                file=sys.stderr,
            )
            return 2
        result = server_verdicts(env, records, cases)

    drift = []
    missing = []
    for field, operator, value, expected in cases:
        key = f"{field}|{operator}|{json.dumps(value)}"
        actual = result["verdicts"].get(key)
        if actual is None:
            missing.append(key)
        elif actual != expected:
            drift.append(
                {
                    "case": key,
                    "committed": expected,
                    "server": actual,
                }
            )

    report = {
        "cases": len(cases),
        "replayed": len(result["verdicts"]),
        "rejected_by_server": result["rejected"],
        "shape_drift": result["shape_drift"],
        "expectation_drift": drift,
        "no_longer_legal": missing,
    }
    if args.as_json:
        print(json.dumps(report, indent=2))
    else:
        print(f"corpus records : {len(records)}")
        print(f"cases in file  : {report['cases']}")
        print(f"replayed       : {report['replayed']}")
        print(f"server refused : {report['rejected_by_server']}")
        for label, items in (
            (
                "corpus no longer round-trips through the database",
                result["shape_drift"],
            ),
            ("cases the server now refuses", missing),
        ):
            if items:
                print(f"\n{label}: {len(items)}")
                for item in items[:20]:
                    print(f"  {item}")
        if drift:
            print(f"\nEXPECTATIONS THE SERVER NO LONGER AGREES WITH: {len(drift)}")
            print(
                "  (either the server's evaluator changed, or this script no "
                "longer rebuilds\n   the record set the corpus was generated "
                "from -- check CREATION_NULLS first)"
            )
            for item in drift[:40]:
                print(
                    f"  {item['case']}: committed={item['committed']} "
                    f"server={item['server']}"
                )
        else:
            print("\nEvery committed expectation still matches filtered_domain(). OK")

    return 1 if (drift or missing or result["shape_drift"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
