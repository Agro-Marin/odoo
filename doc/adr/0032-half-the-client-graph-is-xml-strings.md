# ADR-0032: Half the client's dependency graph is written in XML, as strings

- **Status:** Accepted
- **Date:** 2026-08-14 (retroactive — records a decision already enforced)

## Context

A view arch names a field widget by string, and the runtime looks that key up in
a JavaScript registry. A view names a JS class the same way. A template calls
another template by name, resolved against every template the assets shipped.

**None of those edges is an import**, so every import-reading gate is blind to
all of them. **And so is the ORM**: view validation checks an arch against the
*model*, never against the JavaScript registries. Nothing in either half of the
stack connected the two.

So renaming a registry key is invisible until it runs. Every view naming the old
key still installs, upgrades and loads cleanly, and the failure arrives later as
a **silent** wrong render, where an unknown widget falls back to the default, or
a hard crash when a component with a missing template target first renders. The
audit that prompted this gate called it the largest genuinely missing gate in the
directory.

The same class of blindness ADR-0022 records for objects passed by value and
ADR-0029 for the framework's runtime seams, arriving through a third mechanism:
strings in a markup language, resolved at render time.

## Decision

**What the XML names, some JavaScript must provide, and that is checked.**

Both halves are collected with real parsers, and both choices were forced by
prior mistakes.

**Providers come from JavaScript through a real parser**, not a regex, because
the registration forms alias: an inline registration, a bound category with a
later and possibly chained addition, and this fork's own registration helpers
whose spec object expands to several keys plus aliases. A regex reads one shape
and silently misses the rest — ADR-0021's lesson, and the exact defect the
registry-layering gate documents.

**Consumers come from XML through a real XML parser**, for the same reason in
the other language: an arch is a document, and treating it as text finds
attributes that are not there and misses ones that are.

Template providers are every literal template name the static XML declares, so
the check spans both languages in both directions.

## Alternatives considered

**Extend an import-reading gate.** Rejected on ADR-0022's and ADR-0029's
structural grounds: there is no import edge to extend from. The dependency is a
string in one language resolving against a registration in another.

**Have the ORM's view validation check the registries.** Superficially the right
home, and rejected because it would put a dependency on the JavaScript
registries inside the model layer — unavailable server-side anyway. The check
belongs where both trees can be read as files, not where one is a live runtime.

**Match the registrations with a regex.** Rejected before it was built, on the
strength of two gates here that tried it: registration forms alias, and a
partial match produces a gate that reports clean because it never saw the
provider — the most expensive kind of wrong.

**Rely on the test suites.** A wrong widget key renders the *default* widget.
Not a crash and frequently not a test failure; a view that is quietly wrong in
production.

## Consequences

- Renaming a registry key or a template name fails a gate rather than producing
  a silently wrong render, and the gate names the arch that referenced it.
- **The check spans two languages and two parsers**, so it costs more to
  maintain than a single-language gate and depends on the JS toolchain being
  present.
- Coverage is what static XML names. A registry key built at runtime from a
  computed string is outside it and always will be.
- The gate says nothing about whether a provided widget is the *right* one for
  the field. Existence, not suitability.
- It does not run the reverse direction: a registration nothing names is not an
  error, because a widget may legitimately exist for downstream use.

## Enforcement

One gate in `tooling/architecture/`, declaring `ADR = "0032"`, run by
`.github/workflows/architecture.yml`:

| gate | holds |
|---|---|
| `tooling/architecture/xml_reference_coherence.py` | every registry key and template name a static arch references is provided by some JavaScript or XML in the tree |

`tooling/architecture/test_gate_adr_coverage.py` checks that the citation
resolves to this record and that it is `Accepted`. Run the gate for its live
status.
