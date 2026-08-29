# ADR-0076: Runtime code does not read a docstring

- **Status:** Accepted
- **Date:** 2026-08-29

## Context

Prose comments and docstrings are removed from `odoo/`, `tests/` and `tooling/`
by policy — `0b64c12a5fa` did the sweep, and it is a sweep that will happen
again. In those trees `__doc__` is `None`, and any code that reads it gets
`None`.

That is fine where `None` merely flows. It is not fine where the value is then
used, and the difference is the whole of this record:

```python
description=__doc__.replace("/odoo/upgrade_code", str(UPGRADE))   # AttributeError
fields.Field.__doc__ += """..."""                                 # TypeError
```

Both of those shipped. `odoo/cli/upgrade_code.py` could not print `--help` at
all when run as a script — the standalone path the file reimplements `Command`
precisely to support. `addons/base_sparse_field/models/fields.py` could not be
imported, so the module could not be installed; whoever fixed it left the
diagnosis in a comment above the line.

A third case had no traceback and was worse for it. `odoo-bin help` renders each
command's class docstring, so after the sweep **twelve of fourteen commands
listed blank**, `server` and `shell` among them. Nothing raised. The feature just
stopped saying anything, and stayed that way.

## Decision

**Runtime code does not depend on a docstring being present.** Text a user or an
operator will read is stored in an attribute — `Command.description` — which is
data, and which no strip removes. A docstring may still be read as a *fallback*,
because `None` flowing into an `or` costs nothing.

## Alternatives considered

**Exempt some tree from the strip.** The natural proposal: keep docstrings on
`Command` subclasses, since they are documentation. It re-opens the question the
strip settled, for one directory, and leaves the next reader unable to tell which
files are exempt without consulting a list. The attribute costs one line and is
visible at the point of use.

**Restore the docstrings and forbid stripping them.** Same objection, and it
makes every future sweep a negotiation.

**Let the gate flag every `__doc__` read.** It reports thirty-odd sites across
four repositories, nearly all correctly guarded, and a gate whose findings are
mostly fine is a gate people learn to skip.

## Consequences

- A new command sets `description`; the `test_cli` gate says so in its failure
  message, naming the attribute.
- `Command.parser` and `odoo-bin help` resolve `description or __doc__`, one
  precedence. They disagreed until this record, so a command carrying both
  described itself differently in the two places.
- Reading `__doc__` stays legal wherever `None` is an acceptable value —
  `x.__doc__ or ""`, a comprehension filter, an argument, a return.

## Enforcement

`tooling/architecture/py_docstring_at_runtime.py` fails the build on a read that
would raise: attribute access on `__doc__`, subscripting it, calling a method on
it, or using it as an operand. It is drift-zero across `odoo/`, `addons/` and the
`enterprise` and `agromarin` siblings — there is no debt to pay down, only a
class not to reintroduce. `architecture.yml` runs all four scopes.

The gate deliberately does **not** try to catch the third case above. Whether a
docstring's absence makes an output *wrong* rather than *absent* is a semantic
question, and a gate that guessed at it would be noise. What it catches is the
mechanical class, which is the class that has actually crashed. The blank
`odoo-bin help` is held instead by `test_cli.py::TestCommand.test_help_text`,
which asserts each command carries help text through whichever of the two
sources survives.
