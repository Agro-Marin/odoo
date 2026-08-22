import os
import re
from pathlib import Path

from odoo.tests.common import BaseCase, tagged

WEB_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = WEB_ROOT / "static" / "src"
SERVICES_DTS = SRC_ROOT / "@types" / "services.d.ts"

_CHAIN_REGISTRATION_RE = re.compile(
    r'category\s*\(\s*["\']services["\']\s*\)\s*\.\s*add\s*\(\s*["\']([^"\']+)["\']',
)

_ALIAS_BINDING_RE = re.compile(
    r"(?:const|let|var)\s+(\w+)\s*=\s*registry\s*\.\s*category\s*\("
    r"\s*[\"']services[\"']\s*\)",
)

_INTERFACE_BODY_RE = re.compile(
    r"export\s+interface\s+Services\s*\{([^}]*)\}",
    re.DOTALL,
)
_INTERFACE_KEY_RE = re.compile(
    r'(?:["\']([^"\']+)["\']|([a-zA-Z_][\w.]*))\s*:\s*typeof\s+\w',
)


def _registered_service_keys() -> set[str]:
    keys: set[str] = set()
    for dirpath, _dirnames, filenames in os.walk(SRC_ROOT):
        for filename in filenames:
            if not filename.endswith(".js"):
                continue
            path = Path(dirpath) / filename
            text = path.read_text(encoding="utf-8")
            aliases = {m.group(1) for m in _ALIAS_BINDING_RE.finditer(text)}
            keys.update(
                match.group(1) for match in _CHAIN_REGISTRATION_RE.finditer(text)
            )
            for alias in aliases:
                alias_re = re.compile(
                    rf'\b{re.escape(alias)}\s*\.\s*add\s*\(\s*["\']([^"\']+)["\']',
                )
                keys.update(match.group(1) for match in alias_re.finditer(text))
    return keys


def _typed_service_keys() -> set[str]:
    text = SERVICES_DTS.read_text(encoding="utf-8")
    body_match = _INTERFACE_BODY_RE.search(text)
    if not body_match:
        raise AssertionError(
            f"Could not locate 'export interface Services {{...}}' in {SERVICES_DTS}.",
        )
    body = body_match.group(1)
    keys: set[str] = set()
    keys.update(
        match.group(1) or match.group(2) for match in _INTERFACE_KEY_RE.finditer(body)
    )
    return keys


@tagged("web_unit", "web_typed_services")
class TestTypedServicesConsistency(BaseCase):
    def test_every_registered_service_is_typed(self):
        registered = _registered_service_keys()
        typed = _typed_service_keys()
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
