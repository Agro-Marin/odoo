# ADR-0035: `odoo_rust` is mandatory, and a stale build is refused at import

- **Status:** Accepted
- **Date:** 2026-08-14 (retroactive — records a decision already enforced)

## Context

This fork moved several hot paths into a native extension: the field-cache batch
operations, the id and prefetch helpers, cursor row conversion, JSON fast-clone,
id sorting and the lint scanner. The crate lives in `crates/odoo_rust` and is
built into the environment with maturin.

Two questions, the second easy to get wrong.

**Whether to keep a Python fallback.** A pure-Python path for every accelerated
function makes the extension optional, at the cost of two implementations of
each hot path, both needing tests, and a permanent risk they disagree — a
divergence invisible until the fallback is the one running.

**What a stale build means.** An extension built from older sources and left in
a long-lived virtualenv does not run slower; it runs *differently*. Measured
symptoms: a segfault on a cyclic fast-clone, and silently mis-ordered
timezone-aware columns. **Neither failure names its cause** — the traceback
points at ordinary Python, and the wrong ordering does not raise at all.

CI never encounters this, because every lane builds fresh. It is purely a
developer-machine problem, which is exactly the kind that goes undiagnosed.

## Decision

**The extension is a hard dependency with no fallback, and both its presence and
its freshness are checked at import.**

### 1. Import fails loudly when it is absent

`odoo/init.py` imports it unconditionally and converts the failure into an error
naming the crate, what depends on it, and the command to build it. No degraded
mode, because a degraded mode is the second implementation this decision avoids.

### 2. A stale build is refused, by content

`crates/odoo_rust/build.rs` computes a CRC over the crate's sources —
`Cargo.toml` plus every Rust source file — and stamps it into the binary.
`odoo/init.py` recomputes it from the checkout and refuses to start when the two
disagree, naming the rebuild command and the bypass environment variable.

**A checksum, not a timestamp**, and **CRC-32 rather than a cryptographic
hash**: the threat is an out-of-date file, not a forged one. The two
implementations must agree exactly, which is why the algorithm is pinned in the
crate's comments rather than left to a library default.

The escape hatch is deliberate: a developer who knows their build is current can
skip the check, and the error message says how.

### 3. The Python-to-Rust surface is pinned

Every symbol the core imports without a fallback is listed in
`.github/workflows/rust.yml` and asserted to resolve after a fresh build. That
list is the contract between the two languages, and the thing that would
otherwise rot silently when a Rust function is renamed.

The workflow gates formatting, clippy with warnings as errors, the crate's own
tests, the build, and that symbol contract. **It blocks; it does not warn.**

## Alternatives considered

**Keep a Python fallback for every accelerated function.** Rejected on the cost
of divergence: two implementations of the same hot path, each needing tests, with
no mechanism to prove they agree. The failure mode is the worst available — the
fallback silently behaving differently, discovered only where the extension is
missing.

**Make the extension optional and skip its features when absent.** Same
objection one level up: behaviour would depend on how the environment was built,
so a bug report stops being reproducible without knowing something nobody
records.

**Check freshness by timestamp.** Wrong in both directions: a checkout, a rebase
or a touched file changes mtimes without changing content, and a restored build
can be newer than sources it does not match.

**Use a cryptographic hash.** Answers a threat that does not exist here. The
question is only whether two files came from the same input, and a checksum
answers it at a fraction of the cost — simple enough to be written twice, in two
languages, and be sure they agree.

**Warn instead of refusing.** A warning about a stale build is one line in a log
that will be scrolled past, and the consequence is not a slower run but a
segfault or silently wrong data. Where the failure is silent, the guard has to be
loud.

## Consequences

- Every developer environment needs a Rust toolchain, and a `git pull` touching
  the crate means a rebuild before the server starts. Real recurring friction,
  and the price of one implementation instead of two.
- **The refusal is a hard stop on a machine that was working a minute ago.** The
  error message carries the rebuild command precisely because the person hitting
  it did not choose to.
- The check runs only when the crate directory is present, so a deployment
  installing the built wheel without sources is unaffected.
- The symbol contract must be kept in step by hand when a new unconditional
  import is added — the workflow asserts the list, nothing derives it from the
  call sites. The natural next improvement.
- Nothing here covers the *correctness* of the Rust against the Python it
  replaced. The crate's tests and the framework suites do that; freshness only
  guarantees the binary matches the sources.

## Enforcement

`odoo/init.py` at import time — presence and freshness, on every start.
`.github/workflows/rust.yml` for the crate: formatting, clippy as errors, unit
tests, the maturin build, and the symbol contract.

Not held by a checker in `tooling/architecture/`, so it does not appear in that
directory's coverage pin. Its enforcement is the interpreter refusing to start,
which is stricter than a gate and runs everywhere the code does.
