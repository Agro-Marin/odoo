# ADR-0026: A source file must never be its own generated bridge

- **Status:** Accepted
- **Date:** 2026-08-14 (retroactive — records a decision already enforced)

## Context

The ESM pipeline generates *bridges*: small shims that let a native module reach
a value the legacy loader holds. A bridge re-exports every name of the module it
stands in for, by reading that module out of the loader. Bridges are built at
bundle time, served from a generated path, and **never checked in**.

During work on the bundling code that emits them, four source files were
overwritten with their own generated bridge — three dropdown behaviours and a
metrics service. A bridge for module *X*, written *as* module *X*, reads *X* out
of the loader and re-exports what it finds, which is itself: the module now
evaluates to nothing.

The web client stopped rendering its navbar, and 320 client tests failed across
two layers.

### Every gate ran green, and each was right

This is the part worth recording, because it is not an oversight anyone should
be expected to have avoided. On that tree, every checker in
`tooling/architecture/` passed, along with all of its own tests:

- The named-export gate asks whether an imported *name* is exported. A bridge
  re-exports every name it replaced, so the answer stayed yes. **Names survive;
  only the values behind them are gone.**
- The public-surface gate compares the exported surface against its pin, and
  reported it unchanged, for exactly the same reason.
- The layer, cycle and cohesion gates (ADR-0019) reason about the import graph. A
  bridge imports nothing, so it has no edges to fault — it is *maximally* clean
  by every graph measure.
- The import-resolution gate (ADR-0023) checks that specifiers name real files. A
  bridge contains no specifiers, so there was nothing to check.

Each of those is correct about its own contract. The property none of them holds
is that **a module still evaluates to something.**

## Decision

**No source file may read the module loader for its own specifier.**

That single rule is enough, because it is the defining shape of a self-bridge: a
generated bridge exists precisely to fetch some *other* module out of the loader,
so a file fetching *itself* is either the accident above or a construction with
no meaning.

The check runs over the source tree of every addon, not just the one where the
accident happened. The pipeline that emits bridges is shared, so the failure is
available to every addon that has client source.

### Limits, stated so a green result is not read as more than it is

- **Only self-reference is faulted.** Reading the loader for another module is
  the legitimate use, and is untouched.
- The gate does not verify that any *other* file is what it should be. A source
  file replaced by unrelated wrong content is out of scope, and this record does
  not imply otherwise.

## Alternatives considered

**Extend an existing gate.** The instinct is to add this to the export-coherence
or surface gate, and the incident shows why it does not work: both were green
throughout, correctly, because a bridge preserves every name. To catch this they
would have to reason about *values*, which is a different question from the one
they exist to answer, and answering it would change what they mean.

**Prevent it in the pipeline instead of checking the tree.** Better in principle,
and it is where the bug was. It is also not sufficient: the pipeline is one
producer of these files today, a hand-written mistake or a bad merge produces the
same shape, and the tree is the thing that ships. A check on the artifact holds
regardless of which producer went wrong.

**Add the bridge output path to the ignore rules and rely on that.** Rejected —
the bridges were not in a bridge directory, which is the whole problem. They were
written over source paths, so a path-based rule sees nothing.

**Rely on the test suite, which did catch it.** It caught it at 320 failures
across two layers, with the navbar gone and no indication of the cause. The
suite proves something is broken; this names the file and the reason in one
line, on a checker that runs in about a second.

## Consequences

- The class of failure where a module type-checks, lints, imports cleanly, keeps
  its entire export surface, and evaluates to nothing is closed for the shape
  that produced it.
- The cost is one more checker over the client source, and one more rule for a
  contributor to have never heard of — which is acceptable precisely because
  nobody writes this shape on purpose.
- The gate says nothing about a source file being wrong in any other way. It is
  narrow by construction, and reading it as "the tree is what it should be" would
  be a mistake.
- Nothing prevents the pipeline from writing over source again; this catches the
  result rather than the cause. A fix in the pipeline would be complementary,
  not redundant.

## Enforcement

One gate in `tooling/architecture/`, declaring `ADR = "0026"`, run by
`.github/workflows/architecture.yml`:

| gate | holds |
|---|---|
| `tooling/architecture/js_self_bridge.py` | no source file reads the loader for its own specifier, across every addon's client source |

`tooling/architecture/test_gate_adr_coverage.py` checks that the citation
resolves to this record and that it is `Accepted`. For the gate's live status,
run it — this record does not restate one.
