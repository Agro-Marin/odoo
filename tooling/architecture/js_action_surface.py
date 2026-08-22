#!/usr/bin/env python3
"""Declared-shape gate for the action service — the widest instance in the client.

``env.services.action`` is an ``ActionManager`` instance. Consumers do not
import it; they are handed it, by name, off an ambient object — the same kind of
coupling ADR-0022 records for ``archInfo``, ``env.config`` and the field record,
and blind to every gate built on imports or inheritance for the same reason.
This is a fourth instance of that category, not a new decision.

``action_service_contract.js`` declares the surface. Until this gate existed
nothing checked it against reality, and it had drifted in the direction that
costs something: **the contract under-declared**. Four members were classified
as internal — free to rename — while consumers reached them at 45 non-test call
sites:

  currentController                  25   loadState                          3
  loadAction                         16   uninstallActionCacheInvalidation   1

``uninstallActionCacheInvalidation`` exists solely so ``web_studio`` can call
it, and was on the "nobody reaches this" side of the list.

WHAT IS CHECKED
---------------

Hard zero: every member any present scope reaches on the action service is
named in ``ACTION_MANAGER_SURFACE``. The half that matters in CI is ``web``'s
own reaches, which are checked with no sibling checkout present.

The complementary direction — every declared name exists on the class — is
``sibling_contract.test.js``, which runs the real constructor and so can see
per-instance state that no static scan can.

READING SITES
-------------

Only receivers that are *provably* the action service are counted:

* ``env.services.action.x`` / ``this.env.services.action.x`` / ``services.action.x``
* an identifier bound in the same file by ``useService("action")`` or
  ``env.services.action`` — ``this.actionService = useService("action")`` then
  ``this.actionService.x``, and the bare-``const`` form
* ``am`` / ``this.am`` inside ``webclient/actions/**``, that subtree's parameter
  convention for the manager

``this.action`` is deliberately NOT a reading site even though it is a common
binding for the service, because it is a far more common binding for an action
*record* (``this.action.res_model``, ``this.action.context``). Counting it makes
the gate invent members. That blind spot is the price of not inventing; the
aliasing pass above recovers the real service bindings, which is how the four
missing members were found.

USAGE
-----

  python js_action_surface.py            # gate
  python js_action_surface.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ADR = "0022"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_action_surface")

CONTRACT = ROOT / "addons/web/static/src/webclient/actions/action_service_contract.js"

ACTIONS_SUBTREE = "addons/web/static/src/webclient/actions/"

CONSUMER_ROOTS = (
    ("odoo", ROOT),
    ("enterprise", ROOT.parent / "enterprise"),
    ("agromarin", ROOT.parent / "agromarin"),
    ("design-themes", ROOT.parent / "design-themes"),
)

EXCLUDED_PARTS = frozenset({"node_modules", "lib", "__pycache__"})

# Reaches that are defects in the *consumer*, not surface the service owes.
# Recorded rather than granted: adding them to ACTION_MANAGER_SURFACE would
# declare a contract the manager does not implement, which is the opposite of
# what this gate is for. Each entry is `(scope, file, member)`.
#
# whatsapp: `this.action = useService("action")` then `this.action.id`. The
# manager has no `id` (it has `_id`), so `isRevivingWhatsapp` is `undefined ===
# "revive-whatsapp-conversation"` — always false, and `areAllActionsDisabled`
# in the sibling common/ patch therefore always takes its disabling branch.
#
# Do not "fix" it by renaming the binding: `this.action` IS the action service
# and `onclickWhatsAppChat` (common/composer_patch.js) needs it to `doAction`.
# The defect is the `.id` read, which conflates two different senses of
# "action" — `"revive-whatsapp-conversation"` is a COMPOSER action id from
# `mail.composer/actions`, not an `ir.actions.*` id. Composer exposes no
# "currently selected composer action", so what the getter should read cannot be
# determined from the tree; it needs whoever owns the intent. Recorded here so
# the next reader does not spend the same hour on it.
RECORDED_MISREACHES = frozenset(
    {
        (
            "enterprise",
            "whatsapp/static/src/core/web/composer_patch.js",
            "id",
        ),
    }
)

SURFACE_ENTRY = re.compile(r'^\s*"([A-Za-z_][A-Za-z0-9_]*)",\s*$', re.MULTILINE)

# `this.x = useService("action")` / `const x = useService("action")`, and the
# same two shapes reading `env.services.action` directly.
#
# The `(?!\s*\.)` is load-bearing, and this gate's first run proved it: without
# it, `const currentController = env.services.action.currentController` binds
# `currentController` as if it were the manager, and the gate then reports
# `jsId`, `virtual`, `getLocalState`… as undeclared members of the service.
# They are members of a Controller. An unanchored receiver invents surface.
RECEIVER = (
    r"""(?:useService\(\s*['"]action['"]\s*\)"""
    r"""|(?:this\.)?env\.services\.action(?!\s*\.))"""
)
BIND = re.compile(r"(?:const|let|var)\s+(?P<local>[A-Za-z_$][\w$]*)\s*=\s*" + RECEIVER)
BIND_MEMBER = re.compile(r"this\.(?P<member>[A-Za-z_$][\w$]*)\s*=\s*" + RECEIVER)

DIRECT = re.compile(
    r"""(?:this\.)?env\.services\.action\s*\.\s*(?P<name>[A-Za-z_$][\w$]*)"""
    r"""|(?<![.\w])services\.action\s*\.\s*(?P<name2>[A-Za-z_$][\w$]*)"""
)


@dataclass(frozen=True)
class Reach:
    scope: str
    file: str
    line: int
    member: str
    via: str

    def __str__(self) -> str:
        return f"  {self.member:34s} {self.scope}/{self.file}:{self.line}  ({self.via})"


def declared_surface(contract: Path | None = None) -> frozenset[str]:
    text = (contract or CONTRACT).read_text(encoding="utf-8")
    body = re.search(r"ACTION_MANAGER_SURFACE = \[(.*?)\];", text, re.DOTALL)
    if not body:
        raise SystemExit(
            f"error: ACTION_MANAGER_SURFACE not found in {contract or CONTRACT}"
        )
    return frozenset(SURFACE_ENTRY.findall(body.group(1)))


def _js_files(root: Path):
    for path in root.rglob("static/src/**/*.js"):
        if EXCLUDED_PARTS.isdisjoint(path.parts):
            yield path


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def reaches_in(text: str, in_actions_subtree: bool):
    """Yield ``(member, line, via)`` for every provable action-service reach."""
    for match in DIRECT.finditer(text):
        name = match.group("name") or match.group("name2")
        yield name, _line_of(text, match.start()), "env.services.action"

    locals_ = {m.group("local") for m in BIND.finditer(text)}
    members = {m.group("member") for m in BIND_MEMBER.finditer(text)}
    if in_actions_subtree:
        # `am` is this subtree's parameter name for the manager itself.
        locals_.add("am")
        members.add("am")

    for local in sorted(locals_):
        pattern = re.compile(
            rf"(?<![.\w$]){re.escape(local)}\s*\.\s*([A-Za-z_$][\w$]*)"
        )
        for match in pattern.finditer(text):
            yield match.group(1), _line_of(text, match.start()), local
    for member in sorted(members):
        pattern = re.compile(rf"this\.{re.escape(member)}\s*\.\s*([A-Za-z_$][\w$]*)")
        for match in pattern.finditer(text):
            yield match.group(1), _line_of(text, match.start()), f"this.{member}"


def find_reaches(
    consumer_roots=CONSUMER_ROOTS,
    *,
    surface: frozenset[str] | None = None,
    recorded=RECORDED_MISREACHES,
) -> tuple[list[Reach], int, list[str]]:
    """Scan every present scope for reaches the contract does not declare.

    The roots and the surface are parameters rather than reads of the module
    constants so that `test_js_action_surface.py` can point the scan at a
    synthetic tree. A gate whose core cannot be aimed anywhere is a gate nobody
    has shown can fail, which is indistinguishable from one that never will.
    """
    if surface is None:
        surface = declared_surface()
    undeclared: list[Reach] = []
    scanned = 0
    scopes: list[str] = []
    for scope, root in consumer_roots:
        if not root.is_dir():
            continue
        scopes.append(scope)
        for path in _js_files(root):
            rel = path.relative_to(root).as_posix()
            if "/static/tests/" in f"/{rel}":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError, UnicodeDecodeError:
                continue
            scanned += 1
            in_actions = rel.startswith(ACTIONS_SUBTREE)
            # Fast path, but only where it is sound. Outside the actions subtree
            # every receiver this gate accepts spells "action" somewhere, so a
            # file without the word cannot contain one. Inside it, the `am`
            # convention needs no such word -- `test_js_action_surface.py`
            # caught this by handing the gate exactly that file.
            if not in_actions and "action" not in text:
                continue
            for member, line, via in reaches_in(text, in_actions):
                if member in surface or member.startswith("__"):
                    continue
                if (scope, rel, member) in recorded:
                    continue
                undeclared.append(Reach(scope, rel, line, member, via))
    return undeclared, scanned, scopes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 on findings")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    findings, scanned, scopes = find_reaches()

    if not scanned:
        print("error: no addon static/src trees found", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2))
        return 1 if findings else 0

    print("Action service surface (drift-zero, no tolerated list)")
    print("=" * 72)
    print(f"scopes: {', '.join(scopes)}   files scanned: {scanned}")
    print("-" * 72)
    for finding in sorted(findings, key=lambda f: (f.member, f.scope, f.file)):
        print(finding)
    print("-" * 72)
    if findings:
        members = sorted({f.member for f in findings})
        print(f"\n{len(findings)} reach(es) on {len(members)} undeclared member(s):")
        print(f"  {', '.join(members)}")
        print(
            "\nEach is a contract the action service did not know it had. Add it "
            "to ACTION_MANAGER_SURFACE in action_service_contract.js, or stop "
            "reaching it."
        )
        return 1
    print("\nEvery reached member is declared.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
