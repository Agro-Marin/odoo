"""Default-deny gate over model names carrying "payment".

ADR-0070: the word names nine unrelated things in this tree, and five of them are
called "payment method". The pair that actually misleads is method against
channel -- `account.payment.method` is a capability, `account.payment.method.line`
is that capability wired to a journal and an outstanding account -- and until
2026-08-26 the two shipped the identical `_description`, the only such collision
among the forty payment-named models in the workspace.

Two checks, because the word fails in two ways:

* a **new** model takes the word without saying which of the nine it is, and
* two models take the word and become indistinguishable in the UI, which is what
  a `_description` is for.

Gated at model level, not field level: `payment_method_line_id` alone is 407
occurrences whose spelling is already consistent, and they inherit only their
model's noun. ADR-0048 rejected the same widening for its own vocabulary.

`l10n_*` models are exempt from the allowlist by rule -- those names are Odoo
ecosystem identifiers -- but not from the description check, which asks a
question no ecosystem convention answers.

Usage:
    payment_vocabulary.py --check    # the gate; non-zero on an unlisted model or a shared description
    payment_vocabulary.py --list     # what is pinned, and which category each one is
    payment_vocabulary.py --prune    # drop entries whose model no longer exists
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root, find_workspace, in_workspace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _ast_cache

ADR = "0068"

ROOT = find_odoo_root(Path(__file__).resolve())
ALLOWLIST = Path(__file__).with_name("payment_vocabulary_allowlist.json")

CHECKOUT_ROOTS = ("addons", "odoo/addons")

SIBLING_ROOTS = ("enterprise", "agromarin", "design-themes")

# ADR-0070's nine senses of the word, plus the two annotations a model needs when
# "payment" is not its head noun at all. An entry reads "<category>" or
# "<category> -- <clarifier>".
CATEGORIES = (
    "settlement",
    "provider transaction",
    "method",
    "channel",
    "provider method",
    "till method",
    "fiscal code",
    "due schedule",
    "wizard",
    # "payment" qualifies a different head noun: a provider, a token, a QR code.
    "domain qualifier",
    "test fixture",
)


def scan_roots() -> list[Path]:
    roots = [ROOT / rel for rel in CHECKOUT_ROOTS]
    workspace = find_workspace(ROOT)
    if workspace is not None:
        roots += [workspace / rel for rel in SIBLING_ROOTS]
    return [r for r in roots if r.is_dir()]


def _string_attr(body: list[ast.stmt], attr: str) -> str | None:
    for node in body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id != attr:
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return node.value.value
    return None


def _inherit_names(body: list[ast.stmt]) -> set[str]:
    for node in body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id != "_inherit":
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return {value.value}
        if isinstance(value, ast.List | ast.Tuple):
            return {
                elt.value
                for elt in value.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            }
    return set()


def carries_payment(model: str) -> bool:
    return "payment" in model.split(".")


def is_localisation(model: str) -> bool:
    return model.split(".", maxsplit=1)[0].startswith("l10n_")


def declared_models() -> dict[str, tuple[str | None, str]]:
    """model name -> (declared _description, path of the declaring file)."""
    found: dict[str, tuple[str | None, str]] = {}
    for root in scan_roots():
        for path in sorted(root.glob("*/**/*.py")):
            if "__pycache__" in path.parts or "tests" in path.parts:
                continue
            try:
                tree = _ast_cache.parse_file(path)
            except SyntaxError, UnicodeDecodeError, OSError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                name = _string_attr(node.body, "_name")
                if not name or not carries_payment(name) or name in found:
                    continue
                if name in _inherit_names(node.body):
                    # `_name` alongside `_name` in `_inherit` extends a model; it
                    # does not declare one, and the extension carries no
                    # description of its own.
                    continue
                found[name] = (_string_attr(node.body, "_description"), str(path))
    return found


def load_allowlist() -> dict[str, str]:
    if not ALLOWLIST.exists():
        return {}
    return json.loads(ALLOWLIST.read_text())["models"]


def save_allowlist(models: dict[str, str]) -> None:
    ALLOWLIST.write_text(
        json.dumps(
            {
                "adr": ADR,
                "note": (
                    "Models whose _name carries 'payment' as a dotted component, "
                    "each annotated with which of ADR-0070's nine categories it "
                    "is. `l10n_*` is exempt by rule and is not listed. Add an "
                    "entry only with the category that justifies it; there is no "
                    "--update."
                ),
                "categories": list(CATEGORIES),
                "models": dict(sorted(models.items())),
            },
            indent=2,
        )
        + "\n"
    )


def category_of(annotation: str) -> str:
    return annotation.split("--", maxsplit=1)[0].strip()


def miscategorised() -> dict[str, str]:
    return {
        name: annotation
        for name, annotation in load_allowlist().items()
        if category_of(annotation) not in CATEGORIES
    }


def unlisted(models: dict[str, tuple[str | None, str]]) -> list[str]:
    allowed = load_allowlist()
    return sorted(
        name for name in models if not is_localisation(name) and name not in allowed
    )


def shared_descriptions(
    models: dict[str, tuple[str | None, str]],
) -> dict[str, list[str]]:
    by_description: dict[str, list[str]] = defaultdict(list)
    for name, (description, _path) in models.items():
        if description:
            by_description[description].append(name)
    return {d: sorted(n) for d, n in by_description.items() if len(n) > 1}


def _run_list() -> int:
    for name, category in sorted(load_allowlist().items()):
        print(f"  {name:44} {category}")
    return 0


def _run_prune() -> int:
    if not in_workspace(ROOT):
        print(
            "refusing to prune: the sibling repos are not checked out beside "
            "this one. Run --prune from the full workspace, where every "
            "scanned root exists.",
            file=sys.stderr,
        )
        return 1
    allowed = load_allowlist()
    present = declared_models()
    kept = {k: v for k, v in allowed.items() if k in present}
    save_allowlist(kept)
    for name in sorted(set(allowed) - set(kept)):
        print(f"pruned {name} (model no longer declared)")
    return 0


def _report_unlisted(models: dict, bad: list) -> None:
    print(
        f"ADR-{ADR}: {len(bad)} model name(s) carry 'payment' without an entry "
        "saying which of the nine things they are.\n"
        "A capability is a method; a capability bound to a journal is a channel;\n"
        "an attempt against a PSP is a transaction; money that moved is a\n"
        "settlement. Pick one, then add the model to\n"
        f"{ALLOWLIST.relative_to(ROOT)} with that category.\n",
        file=sys.stderr,
    )
    for name in bad:
        print(f"  {name:44} {models[name][1]}", file=sys.stderr)


def _report_uncategorised(unnamed: dict) -> None:
    print(
        f"\nADR-{ADR}: {len(unnamed)} allowlist entry/entries name no category.\n"
        "An entry reads '<category>' or '<category> -- <clarifier>', where the\n"
        "category is one of: " + ", ".join(CATEGORIES) + ".\n",
        file=sys.stderr,
    )
    for name, annotation in sorted(unnamed.items()):
        print(f"  {name:44} {annotation!r}", file=sys.stderr)


def _report_collisions(models: dict, collisions: dict) -> None:
    print(
        f"\nADR-{ADR}: {len(collisions)} _description string(s) are shared by "
        "more than one payment-named model.\n"
        "A description is what a user reads to tell two models apart, and the\n"
        "pair this gate was written for -- method and channel -- was\n"
        "indistinguishable in the UI for exactly this reason.\n",
        file=sys.stderr,
    )
    for description, names in sorted(collisions.items()):
        print(f"  {description!r}", file=sys.stderr)
        for name in names:
            print(f"      {name:40} {models[name][1]}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="fail on an unlisted model"
    )
    parser.add_argument("--list", action="store_true", help="print the pinned models")
    parser.add_argument("--prune", action="store_true", help="drop vanished models")
    args = parser.parse_args()

    if args.list:
        return _run_list()

    if args.prune:
        return _run_prune()

    models = declared_models()
    if not models:
        print(
            "payment_vocabulary: found no payment-named model at all under "
            + ", ".join(str(r) for r in scan_roots() or ["(no readable root)"])
            + ". A gate with no inputs must refuse rather than report success -- "
            "passing here would mean the check silently stopped covering the tree.",
            file=sys.stderr,
        )
        return 1

    bad = unlisted(models)
    collisions = shared_descriptions(models)
    unnamed = miscategorised()

    if not bad and not collisions and not unnamed:
        if args.check:
            print(
                f"payment_vocabulary: {len(models)} payment-named models scanned, "
                "each listed with its category and each describing itself distinctly"
            )
        return 0

    if bad:
        _report_unlisted(models, bad)
    if unnamed:
        _report_uncategorised(unnamed)
    if collisions:
        _report_collisions(models, collisions)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
