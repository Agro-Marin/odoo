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
    r"(password|secret|api_?key|token|passphrase|private_key|client_secret"
    r"|credential|_key$)",
    re.IGNORECASE,
)

# A key that is published on purpose, or is not a key at all.
#
# `_key$` was added to SECRET because a signing key is a secret whatever it is
# called, and `api_?key` missed every one that does not spell out "api":
# `adyen_hmac_key`, `paymob_hmac_key`, `authorize_signature_key`,
# `authorize_transaction_key` and `openai_key` are all stored secrets the gate
# reported nothing about. But `_key` is also the ordinary English word for a
# dictionary index and for the public half of a keypair, so it needs the
# counterpart these two patterns provide.
#
# Public by design -- these are handed to browsers, and vaulting one protects
# nothing (see PUBLISHED above for the same argument about a Maps key).
PUBLIC_KEY = re.compile(
    r"(public_key|publishable_key|site_key|website_key|client_key)$",
    re.IGNORECASE,
)

# Not a credential in any sense: an index, a lookup, a keyboard key.
NOT_A_KEY = re.compile(
    r"^(cache_key|bucket_key|grouping_key|job_key|period_key|source_key"
    r"|partner_key|zip_key|website_form_key|avatar_cache_key|push_to_talk_key"
    r"|attendance_kiosk_key|identity_key)$",
    re.IGNORECASE,
)

# `_key` names that ARE identifiers, decided per field because the name does not
# say. Each is either the public half of a client-credentials pair, a document
# number printed on the document, or an id the browser already has.
IDENTIFIER_KEYS = frozenset(
    {
        # OAuth client ids. Their client_secret sibling is a secret and is on
        # the backlog; the id is what you send in the clear to ask for a token.
        "delivery_fedex.fedex_developer_key",
        "delivery_fedex_rest.fedex_rest_developer_key",
        "sale_lazada.app_key",
        # The NF-e access key: 44 digits identifying the invoice, printed on the
        # DANFE and quoted back by anyone tracking it.
        "l10n_br_edi.l10n_br_access_key",
        "l10n_br_edi_pos.l10n_br_access_key",
        # An Amazon seller identifier, which appears in the API paths built from
        # it -- `sale_amazon` migrated its refresh token and left this.
        "sale_amazon.seller_key",
        # Rendered into the page for the browser to use, like the Maps key in
        # PUBLISHED above.
        "website.google_analytics_key",
        "website_slides.website_slide_google_app_key",
    }
)

# Names that are *about* a secret rather than one.
ABOUT = re.compile(
    r"(token_type|_expir|has_|is_|use_|show_|_count|_url|_uri|_header|_name"
    r"|_id$|_ids$|_state|_status|_method|_type$)",
    re.IGNORECASE,
)

# A capability we mint so a link works. Whose secret it is decides this, not the
# word "token": moving one into the vault breaks the URL it exists for.
#
# Five names say it on their own.
SHARE = re.compile(
    r"^(share_token|invite_token|document_token|portal_token|signup_token)$"
)

# `access_token`, `token`, `sms_token` and `push_token` do not. The same four
# names carry both kinds, and no pattern separates them -- a generator does not
# either, because `portal.access_token` is minted in a method rather than a
# field default. What separates them is *whom the token authorises*: a visitor
# to one of our records, or us to somebody's API. That is a judgement per field,
# so it is recorded per field.
SHARE_FIELDS = frozenset(
    {
        "appointment.access_token",
        "base.access_token",
        "calendar.access_token",
        "documents.access_token",
        "frontdesk.access_token",
        "hr_contract_salary.access_token",
        "iot.token",  # minted by iot.box._default_token so a box can pair
        "mail.access_token",
        "planning.access_token",
        "point_of_sale.access_token",
        "portal.access_token",
        "pos_enterprise.access_token",
        "rating.access_token",
        "room.access_token",
        "sign.access_token",
        "sign.sms_token",
        "sign.token",
        "social_push_notifications.push_token",
        "spreadsheet_dashboard.access_token",
        "survey.access_token",
        "website.access_token",
        "website_sale.access_token",
        "website_slides.access_token",
    }
)

# A credential to a third party that we hand to the public on purpose.
#
# `website.google_maps_api_key` is served by `/website/google_maps_api_key`,
# which is `auth="public"`: any anonymous visitor can ask for it, because the
# browser needs it to load Maps. Vaulting it protects nothing -- it would be
# encrypted at rest, access-logged and rate-limited, and then handed to whoever
# asked -- and it would put a rate-limited decrypt on an unauthenticated route,
# which is a way to take the site down rather than a way to secure it.
#
# This is NOT the same judgement as SHARE_FIELDS above, which is about tokens
# authorising a visitor to OUR records. This one does authorise us to somebody
# else's API; it is simply not a secret, because we publish it.
#
# The distinction is per field and does not follow the name:
# `website_sale_autocomplete.google_places_api_key` reads almost identically and
# is used server-side, never leaving the backend, so it stays in the backlog.
PUBLISHED = frozenset(
    {
        "website.google_maps_api_key",
    }
)

# Computed *from* a secret, and the point of them is that they are not it.
DERIVED = re.compile(r"(_hash|_masked|_fingerprint|_encrypted|_plain|_display)$")

# A cursor the counterparty hands back so the next call resumes a feed.
# `google_calendar_sync_token` is labelled "Next Sync Token", is read from
# `nextSyncToken` and is sent back as `params['syncToken']`: it is state, it
# authorises nothing, and it changes on every sync -- vaulting it would churn
# the store and its access log for a value that is not a secret.
CURSOR = re.compile(r"(sync_token|page_token|next_token|_cursor)$", re.IGNORECASE)


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


def _hashed_field_names(tree: ast.AST) -> set[str]:
    """Fields this file assigns from a hashing call.

    A hash is not a credential. The vault exists to hand a secret back verbatim,
    and a hash is never handed back -- it is compared. Encrypting one adds a
    reversible layer around a value that was made one-way on purpose, which is
    strictly worse than leaving it alone.

    `DERIVED` catches the ones that say so in their name (`_hash`, `_encrypted`).
    This catches the ones that do not: `website`'s `visibility_password` holds
    `crypt_context.hash(...)` and is named like the plaintext it is not.
    """
    hashed: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and sub.func.attr == "hash"
            for sub in ast.walk(node.value)
        ):
            continue
        for target in node.targets:
            name = getattr(target, "attr", None) or getattr(target, "id", None)
            if name:
                hashed.add(name)
    return hashed


def _is_transient(node: ast.ClassDef) -> bool:
    return bool(node.bases) and "TransientModel" in ast.unparse(node.bases[0])


def _is_stored_field(call: ast.Call) -> bool:
    """Whether the bytes rest in a column.

    Two ways they do not. A `compute`/`related` field without `store=True` is a
    door onto somewhere else. And `store=False` says it outright, which a plain
    field may also do: `sale_amazon`'s LWA access token is declared
    `fields.Char(store=False)` because it lives for one request and is refreshed
    by an API call, so there is no column and nothing to move.
    """
    keywords = {k.arg: k.value for k in call.keywords}
    store = keywords.get("store")
    if isinstance(store, ast.Constant) and store.value is False:
        return False
    if isinstance(store, ast.Constant) and store.value is True:
        return True
    return not ("compute" in keywords or "related" in keywords)


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
            hashed = _hashed_field_names(tree)
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
                    if f"{module}.{name}" in SHARE_FIELDS | PUBLISHED:
                        continue
                    if CURSOR.search(name) or name in hashed:
                        continue
                    if PUBLIC_KEY.search(name) or NOT_A_KEY.match(name):
                        continue
                    if f"{module}.{name}" in IDENTIFIER_KEYS:
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
