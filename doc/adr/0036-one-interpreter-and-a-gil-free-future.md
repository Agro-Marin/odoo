# ADR-0036: One supported interpreter, and an ORM being made ready for its GIL-free build

- **Status:** Accepted
- **Date:** 2026-08-14 (retroactive — records decisions already enforced)

## Context

Upstream Odoo supports a range of Python versions, which is the right choice for
a project whose users control neither their distribution nor their hosting. This
fork does not have that constraint (ADR-0018), and it has a use for the freedom.

**Supporting a range is what makes it impossible to target an interpreter's
capabilities.** Code that must run on several versions can use only their
intersection, and a design that depends on how one of them behaves is not
available at all. The specific capability this fork wants is the free-threaded
build — CPython with the GIL disabled — because the fork's concurrency model is
threads per request and the ceiling on that model is the GIL.

Whether the ORM is ready for that build is not a question anyone can answer by
reading. **Per-cursor transaction isolation means almost no hot state is shared
between request threads**, which is what makes the question tractable at all —
but "almost none" is exactly the kind of claim that is true until it is not, and
the exception is what matters.

The exception was real. `ModelGraph` filled its derived caches lazily, on first
read. Under the GIL that is a well-understood pattern. On a free-threaded build
it is **not corruption** — the interpreter's dicts are thread-safe — but N
threads redundantly rebuild the same trees whenever the cache is cold, so the
pattern that was merely lazy becomes wasteful in proportion to parallelism.
Nothing in the type system, the test suite or any gate distinguishes a
mutation-on-read from a pure lookup.

## Decision

**One supported interpreter, and the shared ORM structures are designed for the
GIL-free build of it.**

### The supported window is a single version

`odoo/release.py` declares `MIN_PY_VERSION` and `MAX_PY_VERSION`, and they are
the same version. That they are equal is itself gated — `test_architecture_doc`
asserts the two constants agree, and asserts that `odoo/init.py` contains the
comparison that acts on the floor.

**The digits are deliberately not written here**, and the gate does not restate
them either. Its own docstring records why: the page used to quote the version
beside the constant names, the digits were only ever correct because a test
compared them to `odoo/release.py`, and a reader can look at that file directly.
What is pinned instead is *the pair that must agree* — the constant and the code
that raises on it. This record follows the same rule, which is the register's
own (`doc/adr/README.md`: cite the file, not the value).

### Each bound is enforced where it is felt, and the responses differ on purpose

| bound | where | response |
|---|---|---|
| below `MIN_PY_VERSION` | `odoo/init.py`, at import | **raises** — before anything else in the package is importable |
| above `MAX_PY_VERSION` | `odoo/cli/server.py`, at server start | **warns** — it runs, and says it is unsupported |
| below `MIN_PG_VERSION` | `odoo/db/pool.py`, on connection | **raises** — at the moment the constraint is first real |

The asymmetry is the decision, not an inconsistency. Below the floor, nothing
will work and the failure should arrive before a confusing traceback can; above
the ceiling, everything probably works and the honest statement is that it is
untested. The database floor cannot be checked before a connection exists, so it
is checked on the first one.

### The ORM's shared structures are made pure-read, and a lane proves it

`ModelGraph.freeze()` precomputes the derived caches at registry-build time, so
reads are lookups rather than fills. `.github/workflows/freethreading.yml` runs
the pure-Python component suites on a free-threaded interpreter, with
`odoo/orm/components/tests/test_model_graph_freethreading.py` hammering a frozen
graph from many threads. Under the GIL that test checks read-consistency; on the
free-threaded build it checks that the race is genuinely gone.

**Scope is the pure-Python components only**, and that is what makes the lane
cheap: those suites need neither the native extension (ADR-0035) nor a real
`import odoo`, so they run on a stock free-threaded wheel with no extra build.

**The lane is warn-only, on purpose and temporarily.** It is informational while
the free-threaded toolchain and ecosystem stabilise, and flips to blocking once
it has been green for a while — the same phased rollout the typecheck lanes used.
A lane that blocks on an ecosystem still in motion gets disabled; one that warns
gets read.

## Alternatives considered

**Support a range of Python versions, as upstream does.** Rejected because the
constraint that makes it necessary does not apply here, and it would forbid the
thing this decision is for: you cannot design for an interpreter's threading
model while also running on interpreters that do not have it. The cost is real —
anyone deploying this fork must provide the interpreter rather than use their
distribution's — and it is the same cost ADR-0035 accepts for the native
extension, for the same kind of gain.

**Refuse to start above the ceiling as well as below the floor.** Rejected as
dishonest about what is known. Below the floor the code genuinely cannot run;
above the ceiling it has merely not been tested, and refusing would claim
knowledge of a failure nobody has observed. A warning states the actual epistemic
position.

**Adopt free-threading now, and run the server on it.** Rejected as premature:
the ecosystem is mid-transition, the native extension and the C-accelerated
dependencies each need their own free-threaded story, and nothing yet requires
the throughput. What is affordable *now* is not shipping designs that would have
to be undone — hence freezing the graph rather than waiting.

**Wait for free-threading to be ready, then look for shared mutable state.**
Rejected because the search is much harder later. Mutation-on-read is invisible
to every gate this fork has; finding it required knowing to look, and each
instance is cheap to fix at the moment it is written and expensive to find in
aggregate afterwards. The lane exists to keep the count at what it is now.

## Consequences

- The fork can make design decisions that depend on interpreter behaviour, which
  is what the single-version window buys and the only reason it is worth its
  cost.
- **Deployment is narrower.** One interpreter version, one database floor, plus
  the native extension. This fork is not something a user installs against
  whatever their distribution ships, and that is a deliberate trade rather than
  an oversight.
- A new mutation-on-read in the frozen structures will show up as a
  free-threading lane failure rather than as a production mystery — but only
  while the lane's scope covers the structure that grew it. Anything outside the
  pure-Python components is not watched.
- **The warn-only lane can be ignored, and eventually will be** if nobody flips
  it. That is the known cost of the phased rollout, and the workflow header
  names the condition for flipping it rather than leaving it to taste.
- The ceiling being a warning means an operator *can* run on a newer interpreter,
  and will get no support for what happens. That is intended, and it is the
  reason the message says "not officially supported" rather than describing a
  fault.

## Enforcement

Three checks in the code itself, none of them a gate in `tooling/architecture/`:
`odoo/init.py` for the floor at import, `odoo/cli/server.py` for the ceiling at
startup, `odoo/db/pool.py` for the database floor on connection. `setup.py`
declares the floor to packaging as well.

`test_architecture_doc` pins the two constants against each other and against the
code that acts on them, and `.github/workflows/freethreading.yml` exercises the
frozen read path under a GIL-free interpreter — warn-only for now, with the
condition for making it blocking stated in the workflow.

Because none of this is a checker in `tooling/architecture/`, this record does
not appear in that directory's coverage pin — the same situation as ADR-0035, and
for the same reason: the enforcement is the code refusing to run.
