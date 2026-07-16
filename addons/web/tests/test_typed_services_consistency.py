"""Source-introspection consistency check for ``static/src/@types/services.d.ts``.

The ``Services`` interface in ``services.d.ts`` drives the typed return of
``useService(K)`` via ``ExtractServiceFactory<Services[K]>``.  When a new
service is registered into ``registry.category("services")`` but not added
to the interface, the call site falls through to ``any`` silently — losing
IDE jump-to-definition, hover types, and ``strictBindCallApply`` checks.

This test enforces the invariant that every service registered under
``addons/web/static/src/`` has a matching key in the ``Services``
interface.  It runs in the unit lane (no DB, no browser) and is fast.

Scope: web's own services only.  Other addons may register services and
augment the ``Services`` interface from their own ``@types`` directory;
their keys are not included here.
"""

import os
import re
from pathlib import Path

from odoo.tests.common import BaseCase, tagged

WEB_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = WEB_ROOT / "static" / "src"
SERVICES_DTS = SRC_ROOT / "@types" / "services.d.ts"

# Matches direct chain: ``registry.category("services").add("KEY", ...``.
# ``\s*`` covers line-breaks and indentation between method calls.
_CHAIN_REGISTRATION_RE = re.compile(
    r'category\s*\(\s*["\']services["\']\s*\)\s*\.\s*add\s*\(\s*["\']([^"\']+)["\']',
)

# Matches an alias binding for ``registry.category("services")``.  Two
# patterns are common:
#   const services = registry.category("services");
#   const serviceRegistry = registry.category("services");
# Without this pass, ``services.add("X", ...)`` registrations are missed.
_ALIAS_BINDING_RE = re.compile(
    r"(?:const|let|var)\s+(\w+)\s*=\s*registry\s*\.\s*category\s*\("
    r"\s*[\"']services[\"']\s*\)",
)

# Matches a key inside the ``Services`` interface body:
#   "KEY": typeof X;       (quoted)
#   KEY: typeof X;          (bare identifier)
# Plus a ``Services`` block-locator regex.
_INTERFACE_BODY_RE = re.compile(
    r"export\s+interface\s+Services\s*\{([^}]*)\}",
    re.DOTALL,
)
_INTERFACE_KEY_RE = re.compile(
    r'(?:["\']([^"\']+)["\']|([a-zA-Z_][\w.]*))\s*:\s*typeof\s+\w',
)


def _registered_service_keys() -> set[str]:
    """Walk static/src/**/*.js and return every key passed to a service
    registration call.

    Two pass per file:
      1. Discover aliases bound to ``registry.category("services")`` so
         calls of the form ``serviceRegistry.add("X", ...)`` are caught.
      2. Match both the direct chain (``category("services").add(...)``)
         and every aliased call.
    """
    keys: set[str] = set()
    for dirpath, _dirnames, filenames in os.walk(SRC_ROOT):
        for filename in filenames:
            if not filename.endswith(".js"):
                continue
            path = Path(dirpath) / filename
            text = path.read_text(encoding="utf-8")
            aliases = {m.group(1) for m in _ALIAS_BINDING_RE.finditer(text)}
            for match in _CHAIN_REGISTRATION_RE.finditer(text):
                keys.add(match.group(1))
            for alias in aliases:
                alias_re = re.compile(
                    rf'\b{re.escape(alias)}\s*\.\s*add\s*\(\s*["\']([^"\']+)["\']',
                )
                for match in alias_re.finditer(text):
                    keys.add(match.group(1))
    return keys


def _typed_service_keys() -> set[str]:
    """Parse services.d.ts and return every key declared inside the
    ``export interface Services { ... }`` block."""
    text = SERVICES_DTS.read_text(encoding="utf-8")
    body_match = _INTERFACE_BODY_RE.search(text)
    if not body_match:
        raise AssertionError(
            f"Could not locate 'export interface Services {{...}}' in {SERVICES_DTS}.",
        )
    body = body_match.group(1)
    keys: set[str] = set()
    for match in _INTERFACE_KEY_RE.finditer(body):
        keys.add(match.group(1) or match.group(2))
    return keys


@tagged("web_unit", "web_typed_services")
class TestTypedServicesConsistency(BaseCase):
    """Every ``registry.category('services').add('K', ...)`` in web must
    have a matching ``K: typeof X`` line in the ``Services`` interface."""

    def test_every_registered_service_is_typed(self):
        registered = _registered_service_keys()
        typed = _typed_service_keys()
        # Sanity: at minimum the well-known core services must be both
        # registered and typed.  Catches regressions where the regex stops
        # matching due to a refactor.
        for required in ("orm", "notification", "dialog", "ui"):
            self.assertIn(
                required,
                registered,
                f"Sanity check: {required!r} not found in registrations — "
                "the registration regex may have drifted.",
            )
            self.assertIn(
                required,
                typed,
                f"Sanity check: {required!r} not found in typed manifest — "
                "the interface-body regex may have drifted.",
            )

        missing = registered - typed
        self.assertFalse(
            missing,
            "These services are registered in web/static/src but not typed "
            f"in {SERVICES_DTS.relative_to(WEB_ROOT)}:\n"
            + "\n".join(f"  - {k}" for k in sorted(missing))
            + "\n\nAdd a corresponding `K: typeof X;` entry to the Services "
            "interface.  Without it, useService('K') returns `any` and "
            "loses type checking at every call site.",
        )

    def test_typed_manifest_has_no_orphan_keys(self):
        """Reverse direction: every key in the Services interface should
        be backed by a real registration somewhere in web/static/src.

        Catches typos (``"web.frequent.emojis"`` vs ``"web.frequent.emoji"``)
        and stale entries left over after a service was deleted.

        Scoped to the local manifest only — other addons that augment
        ``Services`` from their own ``@types`` directory are not checked
        here.
        """
        registered = _registered_service_keys()
        typed = _typed_service_keys()
        orphans = typed - registered
        self.assertFalse(
            orphans,
            f"These keys are typed in {SERVICES_DTS.relative_to(WEB_ROOT)} "
            'but no `registry.category("services").add(K, ...)` call was '
            "found for them under web/static/src:\n"
            + "\n".join(f"  - {k}" for k in sorted(orphans))
            + "\n\nEither the service was deleted (drop the type entry) or "
            "the registration moved to another addon (the type entry should "
            "move too, into that addon's local @types/services.d.ts).",
        )
