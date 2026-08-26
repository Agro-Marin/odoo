# ADR-0063: The qweb compile context separates the compiler's state from the caller's

- **Status:** Accepted
- **Date:** 2026-08-26

## Context

`ir.qweb`'s compiler threads one `dict[str, Any]` named `compile_context`
through every method that turns XML into Python. It is built as

```python
compile_context = self.env.context.copy()
```

and the compiler then writes eleven keys of its own into it: `ref`, `ref_name`,
`ref_xml`, `root`, `template`, `make_name`, `template_functions`,
`_text_concat`, `nsmap`, `iter_directives`, `_qweb_error_path_xml`.

That parameter is not internal. It is the second argument of every
`_compile_directive_*`, `_compile_node`, `_compile_directives` and
`_compile_static_node`, so it is the inheritance contract an addon overrides
against. Inside this workspace, `mail` and `html_editor` both do.

**The two namespaces are not separable by inspection.** `html_editor`'s
`_compile_node` reads

```python
snippet_key = compile_context.get('snippet-key')   # the caller's, via t-options
template = compile_context['ref_name']             # the compiler's
```

two lines apart, with nothing in either expression saying which is which. A
reader cannot tell what a given key is, where it came from, or who is allowed to
set it; neither can a type checker, because the annotation is `dict[str, Any]`
for all of it.

Three consequences follow from the single namespace, and they are the reason
this is a record rather than a cleanup:

- **A caller can address compiler state.** Nothing stops
  `_render(template, values, template_functions=...)`. Every one of the eleven
  happens to be overwritten before it is read, so no collision is live today —
  but that is an accident of ordering, re-established by hand on every change.
- **`iter_directives` is a live iterator stored in a shared dict.** It survives
  only because `for directive in compile_context["iter_directives"]` binds the
  iterator object once, so `_compile_directive_if` recursing into
  `_compile_node`, which reassigns that key, cannot disturb the loop already
  running. The mechanism is an evaluation rule of `for`, not a design.
- **`_qweb_error_path_xml` is one list shared between compile time and render
  time.** `_compile_node` writes all three of its slots for every node it
  compiles; `_resolve_error_frame` reads it during a render.
  `_render_prepared` has to reset it on every render to undo the compiler's
  last write, with a comment explaining why.

## Decision

`compile_context` is a `CompileContext` dataclass with two addressing modes, and
which mode you use says which namespace you mean:

- **Attribute access is the compiler's own state.** `compile_context.ref`,
  `.ref_name`, `.root`, `.make_name`, `.template_functions`, `.text_concat`,
  `.nsmap`, `.directives`, `.error_path_xml`. These are typed fields; a caller
  cannot create one and a typo is an `AttributeError` rather than a `None`.
- **`.get()` and `in` are the caller's context**, unchanged and open-ended:
  `compile_context.get('snippet-key')`, `'raise_on_forbidden_code_for_model' in
  compile_context`. An addon may put anything there through `t-options`, and the
  compiler never needs to know what.

**There is no `__getitem__`.** Subscripting is what made the two indistinguishable,
so removing it is the decision, not an omission.

`nsmap` is a compiler field that is *seeded* from the caller's context, because
it is genuinely both: a `t-call` passes one in its options, and the compiler
mutates it as it descends. That is stated once, on the field.

## Alternatives considered

**Leave it a dict and document the keys.** Rejected. A prose list of a dict's
keys is a second copy of the tree that drifts, which `doc/adr/README.md` names
as its own anti-pattern. It also fixes neither half of the problem: the
ambiguity survives and nothing is typed.

**A dataclass that keeps `__getitem__`, falling back to the context.** This is
the migration-friendly option and it is the one worth arguing against, because
it is what a reviewer will propose. It preserves exactly the defect:
`ctx['ref_name']` and `ctx['snippet-key']` would both work and mean different
things, so the contract stays unreadable — and a caller-supplied `ref_name`
would shadow compiler state through the same door. The compatibility it buys is
compatibility with the thing being removed.

**Two parameters, compiler state and context.** Rejected. It doubles the arity
of every method in the contract to express what one object with two addressing
modes expresses, and it has no answer for `nsmap`, which belongs to both.

**Namespace the compiler's keys inside the dict** (`__qweb_ref`, …). Rejected.
It pays the full cost of renaming the contract and buys only the collision half:
still one namespace, still `Any`, still no discoverability.

## Consequences

- **The cost falls outside this repository.** An addon overriding a
  `_compile_directive_*` and subscripting `compile_context` for a compiler key
  must use the attribute. In this workspace that is `html_editor` (four sites)
  and `mail` (which only tests membership, so is unaffected). A third-party
  addon doing the same gets an unambiguous `TypeError` at compile time, not a
  silent `None`.
- **`iter_directives` and `_qweb_error_path_xml` are named but not cured.** They
  become `.directives` and `.error_path_xml`, typed and documented; the
  re-entrancy of the first and the compile/render sharing of the second are
  properties of how directives recurse, and changing them means changing every
  directive handler's signature. This record does not do that, and says so, so
  that the next reader does not mistake the rename for a fix.
- **The compile cache key is unaffected.** `_get_template_cache_keys()` still
  declares which of the *caller's* context keys a compile may depend on, and
  nothing here checks that a compile reads only those — the hole ADR-0063 does
  not close, and `html_editor`'s `t-install` was one instance of it
  (`40c834be658`).

## Enforcement

**The language holds the split, and three tests hold the language.** `CompileContext`
is a `@dataclass(slots=True)` that defines `get()` and `__contains__` and no
`__getitem__`, so `ctx['ref_name']` is a `TypeError` rather than a second way to
spell compiler state, and `slots=True` makes `ctx.ref_nmae = …` an `AttributeError`
rather than a silently-created field. Neither property is guarded by a gate, and
neither would survive a well-meaning `__getitem__` added for one call site, so
`TestQWebHelpers` in `odoo/addons/base/tests/test_qweb.py` pins all three halves
of the decision: that attribute access and `.get()` of the same key return
different values, that subscripting raises, and that an undeclared field is
refused.

**mypy does not reach this file.** `py_typecheck.yml` runs over
`odoo.{orm,db,libs,http,service,modules}` and, separately, `odoo.tools`;
`odoo/addons/base/` is in none of them, so the field types here are documentation
and an IDE aid, not a checked contract. That is the gap this record leaves open:
a typo in an *existing* field name is caught, a wrong *type* in one is not.

**Nothing enforces the boundary outside this repository**, by construction — the
Consequences above say the cost falls on addons that subscript for a compiler key,
and what they get is the `TypeError`. `libs_facade_check` and the surface gates do
not look at this, because `ir.qweb` is an addon model rather than a framework
facade.
