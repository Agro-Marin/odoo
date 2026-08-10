"""Find ``@api.constrains`` that read fields they do not declare.

An under-declared *compute* goes stale. An under-declared *constraint* does not
run at all: Odoo re-checks a constraint on write only when one of its declared
fields appears in the values, so a constraint that branches on an undeclared
field can be walked straight past by writing that field alone.

Run it the same way as ``depends_audit`` -- against a live registry, and a wide
one, since only installed modules are visible::

    echo 'import sys; sys.path.insert(0, "tooling")
    import constrains_audit; constrains_audit.main(env)' \\
        | odoo-bin shell -d <db> --no-http

Set ``CONSTRAINS_TARGET`` to scope the report to a path.

Only single-segment reads are reported: ``@api.constrains`` does not support
dotted paths, so a read through a relation is a different problem that declaring
cannot fix (the usual answer is a matching constraint on the other model).

**Most hits are not defects.** Triage each against these, in order -- on a mail
run all five were explained by one of the first two:

1. **A database constraint already enforces it.** ``mail.alias.domain``
   ``_check_bounce_catchall_uniqueness`` reads ``name`` without declaring it, but
   ``UNIQUE (bounce_alias, name)`` blocks the colliding rename anyway; declaring
   it would only change which message the user sees.
2. **A constraint on the other side covers the write.** ``mail.activity.plan``
   validates its templates while declaring only ``res_model``, and
   ``mail.activity.plan.template`` carries the matching
   ``@api.constrains("activity_type_id", "plan_id")``. The pair is deliberate and
   documented there.
3. **The field is read only to build the error message** (a ``name`` in a
   ``ValidationError``), so it cannot change the verdict.
4. **The field cannot change**, by an explicit guard in ``write()`` or because it
   is only ever set at creation.

What survives all four is worth a test: write the undeclared field alone and
check the constraint still fires.
"""

import ast
import inspect
import logging
import os
import textwrap

import depends_audit

_logger = logging.getLogger(__name__)

TARGET = os.environ.get("CONSTRAINS_TARGET", "/addons/")
SKIP_PATHS = ("/test_", "/addons/test", "_test/")


def audit(env):
    """Return one finding per constraint method reading undeclared direct fields."""
    findings = []
    seen = set()
    for model_name in sorted(env.registry):
        model = env[model_name]
        try:
            # a callable @api.constrains on an abstract mixin may raise when
            # resolved (hr_skills raises NotImplementedError)
            constraint_methods = list(model._constraint_methods)
        except Exception:
            _logger.debug("cannot resolve constraints of %s", model_name, exc_info=True)
            continue
        for method in constraint_methods:
            raw = getattr(method, "_constrains", ())
            if callable(raw):
                try:
                    raw = raw(model.sudo())
                except Exception:
                    _logger.debug(
                        "cannot resolve callable @api.constrains on %s.%s",
                        model_name,
                        method.__name__,
                        exc_info=True,
                    )
                    continue
            declared = set(raw or ())
            try:
                src_file = inspect.getsourcefile(method)
                source = inspect.getsource(method)
                lineno = inspect.getsourcelines(method)[1]
            except TypeError, OSError:
                continue
            if not src_file or TARGET not in src_file:
                continue
            if any(skip in src_file for skip in SKIP_PATHS):
                continue
            key = (src_file, method.__name__)
            if key in seen:
                continue
            seen.add(key)
            try:
                tree = ast.parse(textwrap.dedent(source))
            except SyntaxError:
                continue
            func = tree.body[0]
            self_name = func.args.args[0].arg if func.args.args else "self"
            reads = depends_audit._Reads(env, model, self_name)
            reads.visit(func)

            # only direct fields of self: constrains cannot express a path
            missing = sorted({p for p in reads.paths if "." not in p} - declared)
            if missing:
                findings.append(
                    {
                        "model": model_name,
                        "method": method.__name__,
                        "file": src_file.split("/addons/")[-1],
                        "line": lineno,
                        "declared": sorted(declared),
                        "missing": missing,
                    }
                )
    return findings


def main(env):
    """Print the findings, grouped by file."""
    findings = audit(env)
    print(f"\n===== {len(findings)} constraints read undeclared fields =====\n")
    for finding in sorted(findings, key=lambda f: (f["file"], f["line"])):
        print(
            f"{finding['file']}:{finding['line']}  {finding['method']}  "
            f"({finding['model']})"
        )
        print(f"    declared: {finding['declared']}")
        print(f"    reads undeclared: {finding['missing']}")
        print()
