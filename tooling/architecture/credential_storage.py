from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import (
    find_odoo_root,
    find_workspace,
    in_workspace,
    sibling_repo_paths,
)

ADR = "0081"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="credential_storage")
ALLOWLIST = Path(__file__).with_name("credential_storage_allowlist.json")

CHECKOUT_ROOTS = ("addons", "odoo/addons")

SKIP_DIRS = frozenset({"__pycache__", "node_modules", ".git", "tests", "migrations"})

# The vault holds its own value; it cannot reference itself.
VAULT_MODULE = "credential"

SECRET = re.compile(
    r"(password|secret|api_?key|token|passphrase|private_key|client_secret|credential)",
    re.IGNORECASE,
)

# Names that are *about* a secret rather than one.
ABOUT = re.compile(
    r"(token_type|_expir|has_|is_|use_|show_|_count|_url|_uri|_header|_name"
    r"|_id$|_ids$|_state|_status|_method|_type$)",
    re.IGNORECASE,
)

# A capability we mint so a link works. Whose secret it is decides this, not the
# word "token": moving one into the vault breaks the URL it exists for.
SHARE = re.compile(
    r"^(access_token|share_token|invite_token|document_token|sms_token|token"
    r"|portal_token|signup_token|push_token)$"
)

# Computed *from* a secret, and the point of them is that they are not it.
DERIVED = re.compile(r"(_hash|_masked|_fingerprint|_encrypted|_plain|_display)$")


@dataclass(frozen=True, order=True)
class Finding:
    module: str
    field: str
    path: str
    line: int

    @property
    def key(self) -> str:
        return f"{self.module}.{self.field}"

    def __str__(self) -> str:
        return f"{self.path}:{self.line}  {self.key}"


def scan_roots() -> list[Path]:
    roots = [ROOT / rel for rel in CHECKOUT_ROOTS]
    if find_workspace(ROOT) is not None:
        roots += sibling_repo_paths(ROOT)
    return [r for r in roots if r.is_dir()]


def module_names() -> dict[str, str]:
    found: dict[str, str] = {}
    for root in scan_roots():
        for manifest in root.glob("*/__manifest__.py"):
            found.setdefault(manifest.parent.name, str(root))
    return found


def _is_transient(node: ast.ClassDef) -> bool:
    return bool(node.bases) and "TransientModel" in ast.unparse(node.bases[0])


def _is_stored_field(call: ast.Call) -> bool:
    """A door is not a store: a compute/related field with no `store=True`."""
    keywords = {k.arg: k.value for k in call.keywords}
    computed = "compute" in keywords or "related" in keywords
    stored = (
        isinstance(keywords.get("store"), ast.Constant)
        and keywords["store"].value is True
    )
    return stored or not computed


def findings() -> list[Finding]:
    found: list[Finding] = []
    for root in scan_roots():
        for path in root.rglob("*.py"):
            if SKIP_DIRS & set(path.parts):
                continue
            module = path.relative_to(root).parts[0]
            if module == VAULT_MODULE:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef) or _is_transient(node):
                    continue
                for statement in node.body:
                    if not (
                        isinstance(statement, ast.Assign)
                        and isinstance(statement.value, ast.Call)
                    ):
                        continue
                    call = statement.value
                    owner = getattr(call.func, "value", None)
                    if getattr(owner, "id", "") != "fields":
                        continue
                    if getattr(call.func, "attr", "") not in ("Char", "Text"):
                        continue
                    name = getattr(statement.targets[0], "id", "")
                    if not SECRET.search(name) or ABOUT.search(name):
                        continue
                    if SHARE.match(name) or DERIVED.search(name):
                        continue
                    if not _is_stored_field(call):
                        continue
                    found.append(
                        Finding(
                            module=module,
                            field=name,
                            path=str(path.relative_to(root.parent)),
                            line=statement.lineno,
                        )
                    )
    return sorted(found)


def load_allowlist() -> dict[str, str]:
    if not ALLOWLIST.exists():
        return {}
    return json.loads(ALLOWLIST.read_text())["fields"]


def save_allowlist(fields: dict[str, str]) -> None:
    ALLOWLIST.write_text(
        json.dumps(
            {
                "adr": ADR,
                "note": (
                    "Stored Char/Text fields holding a third-party secret, which "
                    "belong in credential.credential. This list is the backlog: an "
                    "entry comes off when the module migrates its value into the "
                    "vault and keeps a Many2one where the Char was. There is no "
                    "--update, because a flag that rewrote the list to whatever the "
                    "tree holds would let the next one in silently."
                ),
                "fields": dict(sorted(fields.items())),
            },
            indent=2,
        )
        + "\n"
    )


def offenders() -> list[Finding]:
    allowed = load_allowlist()
    return [finding for finding in findings() if finding.key not in allowed]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ADR-0081: a credential is stored in the vault, and nowhere else.",
    )
    parser.add_argument(
        "--check", action="store_true", help="fail on an unlisted field"
    )
    parser.add_argument("--count", action="store_true", help="print the offender count")
    parser.add_argument("--list", action="store_true", help="print the pinned fields")
    parser.add_argument("--prune", action="store_true", help="drop migrated fields")
    args = parser.parse_args()

    if args.list:
        for key, why in sorted(load_allowlist().items()):
            print(f"  {key:56} {why}")
        return 0

    if args.prune:
        if not in_workspace(ROOT):
            print(
                "refusing to prune: the sibling repos are not checked out beside "
                "this one, so a field that is merely out of scope would read as "
                "migrated. Run --prune from the full workspace.",
                file=sys.stderr,
            )
            return 1
        allowed = load_allowlist()
        present = {finding.key for finding in findings()}
        kept = {k: v for k, v in allowed.items() if k in present}
        for key in sorted(set(allowed) - set(kept)):
            print(f"pruned {key} (no longer a stored plaintext credential)")
        save_allowlist(kept)
        return 0

    present = module_names()
    if not present:
        print(
            "credential_storage: found no module at all under "
            + ", ".join(str(r) for r in scan_roots() or ["(no readable root)"])
            + ". A gate with no inputs must refuse rather than report success -- "
            "passing here would mean the check silently stopped covering the tree.",
            file=sys.stderr,
        )
        return 1

    bad = offenders()

    if args.count:
        print(len(bad))
        return 0

    if not bad:
        if args.check:
            print(
                f"credential_storage: {len(present)} modules scanned, no stored "
                "credential without an entry saying why"
            )
        return 0

    print(
        f"ADR-{ADR}: {len(bad)} field(s) store a third-party secret in the clear.\n"
        "`credential.credential` encrypts at rest, fingerprints for comparison "
        "without decrypting,\n"
        "access-logs every read and rate-limits it. Hold a Many2one to one "
        "instead of the value.\n"
        "\n"
        "A share token you mint, a compute/inverse door onto a hash, and a "
        "*_hash companion are\n"
        "none of them this, and the scan already excludes them -- if one reaches "
        "here, the\n"
        "classifier is wrong and that is the bug to fix, not the field.\n"
        f"Otherwise add it to {ALLOWLIST.relative_to(ROOT)} with the reason it "
        "has not moved yet.\n",
        file=sys.stderr,
    )
    for finding in bad:
        print(f"  {finding}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
