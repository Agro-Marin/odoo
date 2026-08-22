# ADR-0026: A source file must never be its own generated bridge

- **Status:** Accepted
- **Date:** 2026-08-14 (retroactive — records a decision already enforced)

## Context

The ESM pipeline generates *bridges*: shims letting a native module reach a
value the legacy loader holds. A bridge re-exports every name of the module it
stands in for, by reading that module out of the loader. Bridges are built at
bundle time, served from a generated path, and never checked in.

During work on the bundling code that emits them, four source files were
overwritten with their own generated bridge — three dropdown behaviours and a
metrics service. A bridge for module *X*, written *as* module *X*, reads *X* out
of the loader and re-exports what it finds, which is itself: the module
evaluates to nothing.

The web client stopped rendering its navbar, and 320 client tests failed across
two layers.

### Every gate ran green, and each was right

- The named-export gate asks whether an imported *name* is exported. A bridge
  re-exports every name it replaced, so the answer stayed yes. **Names survive;
  only the values behind them are gone.**
- The public-surface gate compares the exported surface against its pin, and
  reported it unchanged, for the same reason.
- The layer, cycle and cohesion gates (ADR-0019) reason about the import graph. A
  bridge imports nothing, so it has no edges to fault — *maximally* clean by
  every graph measure.
- The import-resolution gate (ADR-0023) checks that specifiers name real files. A
  bridge contains no specifiers.

Each is correct about its own contract. The property none holds: **a module
still evaluates to something.**

## Decision

**No source file may read the module loader for its own specifier.**

That rule is enough, because it is the defining shape of a self-bridge: a
generated bridge exists to fetch some *other* module out of the loader, so a
file fetching itself is either this accident or a construction with no meaning.

The check runs over the source tree of every addon. The pipeline that emits
bridges is shared, so the failure is available to every addon with client
source.

### Limits, stated so a green result is not read as more than it is

- **Only self-reference is faulted.** Reading the loader for another module is
  the legitimate use, and is untouched.
- The gate does not verify that any other file is what it should be. A source
  file replaced by unrelated wrong content is out of scope.

## Alternatives considered

**Extend an existing gate.** The instinct is to add this to the export-coherence
or surface gate; the incident shows why it fails. Both were green throughout,
correctly, because a bridge preserves every name. Catching this means reasoning
about *values*, a different question from the one they exist to answer.

**Prevent it in the pipeline instead of checking the tree.** Better in
principle, and where the bug was. Not sufficient: the pipeline is one producer
today, a hand-written mistake or a bad merge produces the same shape, and the
tree is what ships. A check on the artifact holds regardless of the producer.

**Add the bridge output path to the ignore rules.** Rejected — the bridges were
not in a bridge directory, which is the whole problem. They were written over
source paths, so a path-based rule sees nothing.

**Rely on the test suite, which did catch it.** At 320 failures across two
layers, with the navbar gone and no indication of cause. The suite proves
something is broken; this names the file and the reason in one line, in about a
second.

## Consequences

- The class of failure where a module type-checks, lints, imports cleanly, keeps
  its entire export surface and evaluates to nothing is closed for the shape
  that produced it.
- Cost: one more checker, and one more rule a contributor has never heard of —
  acceptable because nobody writes this shape on purpose.
- The gate says nothing about a source file being wrong in any other way.
  Reading it as "the tree is what it should be" would be a mistake.
- Nothing prevents the pipeline writing over source again; this catches the
  result rather than the cause. A pipeline fix would be complementary.

## Enforcement

One gate in `tooling/architecture/`, declaring `ADR = "0026"`, run by
`.github/workflows/architecture.yml`:

| gate | holds |
|---|---|
| `tooling/architecture/js_self_bridge.py` | no source file reads the loader for its own specifier, across every addon's client source |

`tooling/architecture/test_gate_adr_coverage.py` checks that the citation
resolves to this record and that it is `Accepted`. Run the gate for its live
status.
