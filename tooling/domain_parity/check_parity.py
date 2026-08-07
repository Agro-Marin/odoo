#!/usr/bin/env python
"""Re-derive `domain_server_parity.test.js`'s expectations from a live server.

The test compares `Domain.contains` against a *committed snapshot* of what
`filtered_domain()` answered. That is the right shape for a fast JS suite, but
it leaves the snapshot's provenance in a docstring: if the server's evaluator
changes, the recorded expectations quietly become fiction and the JS test keeps
passing against them.

This closes that loop. It reads the corpus and the case grid straight out of the
committed test file, replays every case through `filtered_domain()` on a real
database, and reports any expectation the server no longer agrees with.

    python tooling/domain_parity/check_parity.py --database <db>
    python tooling/domain_parity/check_parity.py --database <db> --json

Exit status is 1 on any drift, so it can be wired into CI next to the other
gates. Nothing is written to the database: the records live inside a savepoint
that is always rolled back.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

# Located by marker, not by counting parents — see _repo_root. This was the last
# tool still counting (``parents[2]``), and the one no agreement test covered.
REPO_ROOT = find_odoo_root(pathlib.Path(__file__).resolve(), tool="check_parity")
TEST_FILE = REPO_ROOT / "addons/web/static/tests/core/domain_server_parity.test.js"

# The corpus was generated on a database WITH the unaccent extension, and the
# test pins `session.has_unaccent = true` to match. Re-deriving on a database
# without it would "find" a divergence in every accent-folding case.
UNACCENT_REQUIRED = True

# The committed corpus is what `read()` returned, and `read()` is lossy: a NULL
# numeric column and a stored 0 both read back as 0. The two do NOT filter
# alike -- on `partner_latitude`, `like '_'` matches the stored 0 and not the
# NULL, and `=like '\\'` does the reverse -- so a record set rebuilt naively
# from the corpus disagrees with the snapshot on 12 cases while both are
# correct. These are the columns the corpus rows left unset, by index, which is
# the one thing the corpus itself cannot carry.
CREATION_NULLS = {
    0: ("partner_latitude",),
}


def extract_arrays(test_file: pathlib.Path) -> tuple[list[dict], list[list]]:
    """Read `RECORDS` and `CASES` out of the test file.

    Evaluated with node rather than pattern-matched: they are JS literals, not
    JSON (unquoted keys, `\\u` escapes), and a bespoke parser here would be one
    more thing that can silently disagree with the file it is meant to mirror.
    """
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
    """`null` in the JS corpus is Python's `None`; everything else is literal."""
    return value


def server_verdicts(env, records: list[dict], cases: list[list]) -> dict:
    """Replay every case through `filtered_domain()`; never commits."""
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
                # Domains the server rejects outright are excluded from the
                # corpus at generation time; pinning either verdict would pin
                # a fiction. Count them so a change in what is legal shows up.
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
            # Exit 2, not 0. A run that verified nothing is not a run that
            # passed, and this is the one branch where the difference is
            # invisible: the corpus stays green in CI while no case was
            # replayed. Same code the sibling gates use for "could not run"
            # (tooling/ratchet, tooling/typecheck/scope_gate).
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
