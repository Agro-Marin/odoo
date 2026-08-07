"""Generative differential: the restore scanner versus the real ``psql``.

``test_psql_scanner_differential`` compares the two on a FIXED corpus of seven
attacks — each one a bypass that was found by hand and cost an audit to find.
This generalises that comparison: dump-shaped SQL is BUILT from a grammar of the
lexical contexts the scanner models (plain and escape string literals, dollar
bodies tagged and untagged, line and block comments, ``COPY`` data blocks,
``\\restrict`` wrappers, ``$``-bearing identifiers, and unterminated variants of
each), with a shell payload placed either where ``psql`` executes it or where
``psql`` treats it as data.

The property is the same one-way implication, and for the same reason:

    the canary fired  =>  the scanner rejected

The converse is deliberately not asserted.  The scanner may refuse things psql
would ignore — it refuses an over-long SQL line, for instance — and a refused
restore is a safe outcome where a silent execution is not.

Why generative, given the scanner already has 76 unit tests and the fixed
corpus above: a mutation sweep over ``_dump_scanner`` (159 operator mutations,
gated against BOTH this package and ``tests/service``) left 71 alive — 45%,
against 0-28% for every other module in ``odoo/service``.  A lexer's unit tests
necessarily assert outcomes on inputs someone thought of, and the scanner's job
is defined entirely by agreement with a program nobody here wrote.  This closes
that loop for inputs nobody thought of.

Seeds are fixed and the case count is bounded, so a failure names a seed that
reproduces it exactly and the suite stays inside its time budget.  Run the same
generator over a wider range while investigating, **from the repo root**::

    python -m tests.contract.test_psql_scanner_fuzz <scratch-db> 3000

It must be ``-m``: this module imports ``odoo.service._dump_scanner`` (so the
repo root has to be on ``sys.path``) and ``.conftest`` (a relative import, so
the module has to be loaded as part of a package). Running the file as a path —
``python tests/contract/test_psql_scanner_fuzz.py`` — satisfies neither and dies
before ``__main__``, which is why the entry point below had never actually been
run as it was previously documented.
"""

import random
import subprocess

from odoo.service._dump_scanner import _find_disallowed_psql_meta_command

from .conftest import requires_pg, requires_psql

# Bounded so the contract suite stays fast; a case costs roughly one psql
# start-up.  3000 seeds were run while adding this — 0 bypasses, with psql
# really executing the payload in 492 of them and the scanner flagging 1626.
# These 150 are the regression slice.
CASES = 150

_RESTRICT_KEY = "abc123"


def _grammar(rng, payload):
    """(benign, hiding, executing, tricky) fragment pools for one case."""
    benign = [
        "SELECT 1;",
        f"CREATE TEMP TABLE t_{rng.randint(0, 9999)} (a text);",
        "-- an ordinary comment",
        "/* a block comment */",
        "SELECT 'a plain literal';",
        "SELECT E'esc\\\\naped';",
        "SELECT $$dollar body$$;",
        "SELECT $tag$tagged body$tag$;",
        "SELECT 1 AS money$usd;",
    ]
    # psql reads these as data or text: it must NOT execute them, and the
    # scanner must not flag them either (a real dump may contain any of them).
    hiding = [
        f"SELECT '{payload}';",
        f"SELECT $${payload}$$;",
        f"SELECT $t${payload}$t$;",
        f"-- {payload}",
        f"/* {payload} */",
        (
            f"CREATE TEMP TABLE c_{rng.randint(0, 9999)} (a text);\n"
            f"COPY c_{rng.randint(0, 9999)} (a) FROM stdin;\n{payload}\n\\."
        ),
    ]
    # psql executes these.  The scanner MUST reject every one.
    executing = [
        payload,
        f"SELECT 1; {payload}",
        f"\\restrict {_RESTRICT_KEY}\n{payload}\n\\unrestrict {_RESTRICT_KEY}",
        f"SELECT 1 \\gexec\n{payload}",
    ]
    # Shapes that probe the lexer's context bookkeeping, where the two lexers
    # have historically disagreed.  Which side executes is the point of the test.
    tricky = [
        f"SELECT 1 AS a$b$c;\n{payload}",
        f"SELECT 1$t$ body $t$;\n{payload}",
        f"SELECT fooE'x';\n{payload}",
        f"COPY (SELECT 1) TO STDOUT; -- FROM stdin\n{payload}",
        f'"COPY" AS x FROM stdin;\n{payload}',
        f"SELECT 'unterminated\n{payload}",
        f"SELECT $$unterminated\n{payload}",
        f"/* unterminated\n{payload}",
    ]
    return benign, hiding, executing, tricky


def build_case(seed, canary):
    """Deterministically build one dump-shaped file for ``seed``."""
    rng = random.Random(seed)
    benign, hiding, executing, tricky = _grammar(rng, f"\\! touch {canary}")
    parts = [f"\\restrict {_RESTRICT_KEY}"] if rng.random() < 0.3 else []
    wrapped = bool(parts)
    parts.extend(rng.choice(benign) for _ in range(rng.randint(0, 4)))
    parts.append(
        rng.choice(rng.choices([hiding, executing, tricky], weights=[3, 3, 4], k=1)[0])
    )
    parts.extend(rng.choice(benign) for _ in range(rng.randint(0, 3)))
    if wrapped:
        parts.append(f"\\unrestrict {_RESTRICT_KEY}")
    return "\n".join(parts) + "\n"


@requires_pg
@requires_psql
class TestScannerHasNoBypassUnderFuzz:
    def test_anything_psql_executes_is_rejected(self, tmp_path, run_psql):
        """The whole property, over ``CASES`` generated dumps."""
        bypasses, executed, flagged = [], 0, 0
        for seed in range(CASES):
            canary = tmp_path / f"canary_{seed}"
            sql = build_case(seed, canary)
            path = tmp_path / f"case_{seed}.sql"
            path.write_text(sql, encoding="latin-1")

            rejected = _find_disallowed_psql_meta_command(sql) is not None
            flagged += rejected
            run_psql(path)
            if canary.exists():
                executed += 1
                canary.unlink()
                if not rejected:
                    bypasses.append((seed, sql))

        assert not bypasses, (
            f"BYPASS: psql executed the payload and the scanner reported the "
            f"file as safe. Restoring such an archive runs arbitrary shell "
            f"commands as the Odoo service account. First failing seed "
            f"{bypasses[0][0]}:\n{bypasses[0][1]!r}"
        )
        # Guards against the whole test passing vacuously: if nothing executed,
        # the implication above is satisfied by an empty antecedent and proves
        # nothing.  Measured over 3000 seeds, 16% of cases execute the payload.
        assert executed > 0, (
            "no generated case executed the payload, so the differential "
            "compared nothing (check psql flags, permissions, or ON_ERROR_STOP "
            "aborting every case before it reaches the payload)"
        )
        assert flagged > 0, "the scanner flagged nothing at all"

    def test_the_generator_is_deterministic(self, tmp_path):
        """A failure must name a seed that reproduces it."""
        a = build_case(7, tmp_path / "c")
        b = build_case(7, tmp_path / "c")
        assert a == b
        assert build_case(8, tmp_path / "c") != a


if __name__ == "__main__":  # pragma: no cover - investigation entry point
    import pathlib
    import sys
    import tempfile

    db, count = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 1000
    out = pathlib.Path(tempfile.mkdtemp(prefix="scanner_fuzz_"))
    found = 0
    for seed in range(count):
        canary = out / f"canary_{seed}"
        sql = build_case(seed, canary)
        case = out / f"case_{seed}.sql"
        case.write_text(sql, encoding="latin-1")
        rejected = _find_disallowed_psql_meta_command(sql) is not None
        subprocess.run(
            ["psql", "-d", db, "-q", "-v", "ON_ERROR_STOP=1", "-f", str(case)],
            check=False,
            capture_output=True,
            timeout=30,
        )
        if canary.exists():
            canary.unlink()
            if not rejected:
                found += 1
                print(f"BYPASS seed={seed}\n{sql!r}\n")
    print(f"{count} cases, {found} bypasses")
