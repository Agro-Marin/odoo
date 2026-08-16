# ADR-0035: `odoo_rust` is mandatory, and a stale build is refused at import

- **Status:** Accepted
- **Date:** 2026-08-14 (retroactive — records a decision already enforced)

## Context

This fork moved several hot paths into a native extension: the field-cache batch
operations, the id and prefetch helpers, cursor row conversion, JSON fast-clone,
id sorting and the lint scanner. The crate lives in `crates/odoo_rust` and is
built into the environment with maturin.

Two questions had to be answered, and the second is the one that is easy to get
wrong.

**Whether to keep a Python fallback.** A pure-Python path for every accelerated
function would make the extension optional, at the cost of two implementations of
each hot path, both needing tests, and a permanent risk that they disagree — the
kind of divergence that is invisible until the fallback is the one running.

**What a stale build means.** This is not the usual "recompile for speed"
situation. An extension built from older sources and left in a long-lived
virtualenv does not run slower; it runs *differently*. Measured symptoms
included a segfault on a cyclic fast-clone and silently mis-ordered
timezone-aware columns, and **neither failure names its cause** — the traceback
points at ordinary Python, and the wrong ordering does not raise at all.

CI never encounters this, because every lane builds the extension fresh. It is
purely a developer-machine problem, which is exactly the kind that goes
undiagnosed for a long time.

## Decision

**The extension is a hard dependency with no fallback, and both its presence and
its freshness are checked at import.**

### 1. Import fails loudly when it is absent

`odoo/init.py` imports it unconditionally and converts the failure into an error
that names the crate, what depends on it, and the command to build it. There is
no degraded mode, because a degraded mode is the second implementation this
decision exists to avoid.

### 2. A stale build is refused, by content

`crates/odoo_rust/build.rs` computes a CRC over the crate's sources —
`Cargo.toml` plus every Rust source file — and stamps it into the binary.
`odoo/init.py` recomputes the same value from the checkout and refuses to start
when the two disagree, naming both the rebuild command and the environment
variable that bypasses the check.

**A checksum, not a timestamp**, and **CRC-32 rather than a cryptographic hash**:
the threat is an out-of-date file, not a forged one. The two implementations —
one in Rust, one in Python — must agree exactly, which is why the algorithm is
pinned in the crate's own comments rather than left to a library default.

The escape hatch exists and is deliberate: a developer who knows their build is
current can skip the check, and the error message says how.

### 3. The Python-to-Rust surface is pinned

Every symbol the core imports without a fallback is listed in
`.github/workflows/rust.yml` and asserted to resolve after a fresh build. That
list is the contract between the two languages, and it is the thing that would
otherwise rot silently when a Rust function is renamed.

The workflow gates formatting, clippy with warnings as errors, the crate's own
tests, the build itself and that symbol contract. **It blocks; it does not
warn.**

## Alternatives considered

**Keep a Python fallback for every accelerated function.** Rejected on the cost
of divergence: two implementations of the same hot path, each needing its own
tests, with no mechanism to prove they agree. The failure mode is the worst
available — the fallback silently behaving differently from the accelerated path,
discovered only on a machine where the extension is missing. The fork's standing
position is that a second copy drifts, and this would be a second copy of the
ORM's hottest code.

**Make the extension optional and skip its features when absent.** Same
objection one level up: it makes behaviour depend on how the environment was
built, so a bug report stops being reproducible without knowing something nobody
records.

**Check freshness by timestamp.** Rejected because it is wrong in both
directions: a checkout, a rebase or a touched file changes mtimes without
changing content, and a restored build can be newer than sources it does not
match. Content is the property that matters.

**Use a cryptographic hash.** Rejected as answering a threat that does not exist
here. Nobody is forging a build; the question is only whether two files were
generated from the same input, and a checksum answers it at a fraction of the
cost — with an implementation simple enough to be written twice, in two
languages, and be sure they agree.

**Warn instead of refusing.** Rejected on what the failure looks like. A warning
about a stale build is one line in a log that will be scrolled past, and the
consequence is not a slower run but a segfault or silently wrong data. Where the
failure is silent, the guard has to be loud.

## Consequences

- Every developer environment needs a Rust toolchain, and a `git pull` that
  touches the crate means a rebuild before the server will start. That is real,
  recurring friction and it is the price of having one implementation instead of
  two.
- **The refusal is a hard stop on a machine that was working a minute ago**,
  which is startling the first time. The error message carries the rebuild
  command precisely because the person hitting it did not choose to.
- The check runs only when the crate directory is present, so a deployment
  installing the built wheel without the sources is unaffected.
- The symbol contract must be kept in step by hand when a new unconditional
  import is added — the workflow asserts the list, but nothing derives the list
  from the call sites. That gap is real and is the natural next improvement.
- Nothing here covers the *correctness* of the Rust against the Python it
  replaced. The crate's own tests and the framework suites do that; freshness
  only guarantees that the binary matches the sources in the checkout.

## Enforcement

`odoo/init.py` at import time — presence and freshness, on every start.
`.github/workflows/rust.yml` for the crate itself: formatting, clippy as errors,
unit tests, the maturin build, and the symbol contract that the core's
unconditional imports resolve.

This decision is not held by a checker in `tooling/architecture/`, and so does
not appear in that directory's coverage pin. Its enforcement is the interpreter
refusing to start, which is stricter than a gate and runs everywhere the code
does.
