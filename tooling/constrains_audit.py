"""Constraints that read a field they do not declare — the `@api.constrains` twin.

The same shape as `depends_audit`, one decorator over: `@api.constrains` names
the fields whose change re-runs the check, and a constraint that reads a field it
did not name is simply not re-run when that field changes. The failure is silent
and one-directional — the record saves, and the invariant the constraint exists
to hold is not held.

Run under `odoo shell`, against the widest registry available, for the reason
`depends_audit`'s docstring gives:

    echo 'from tooling.constrains_audit import main; main(env)' \
        | odoo-bin shell -c <conf> -d <db> --no-http

    CONSTRAINS_TARGET=/addons/sale/ ...     # narrow it; default is /addons/

Shares `depends_audit`'s reader and its resolution, which is why it is beside it
and not a copy of it. It gates nothing, for the same reason: the answer depends
on what is installed.
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
    findings = []
    seen = set()
    for model_name in sorted(env.registry):
        model = env[model_name]
        try:
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
