#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _repo_root import find_odoo_root, find_workspace, sibling_repo_paths

ROOT = find_odoo_root(Path(__file__).resolve(), tool="patchorder")

_DESCRIPTION = "Cross-repo staleness sweep for mail's double-patch allowlist."

ALLOWLIST_REL = "addons/mail/static/tests/core/patch_order_audit.test.js"
MIN_SITES = 2

_PATCH_CALL = re.compile(r"(?<![.\w])patch\(\s*")
_CONST_OBJ = re.compile(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*\{")
_KEY = re.compile(
    r"^[ \t]*(?:async[ \t]+)?(?:get[ \t]+|set[ \t]+|static[ \t]+)?"
    r"(?:\*[ \t]*)?(\[?[A-Za-z_$][\w$.]*\]?)[ \t]*[(:]",
    re.MULTILINE,
)
_ENTRY = re.compile(r'^\s*"([^"]+ :: [^"]+)",\s*$', re.MULTILINE)


def read_allowlist(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    start = text.find("const KNOWN_DOUBLE_PATCHES = new Set([")
    if start < 0:
        raise SystemExit(
            f"patchorder: no `KNOWN_DOUBLE_PATCHES` Set literal in {path} — the "
            f"allowlist moved or was renamed. Refusing to sweep against nothing."
        )
    end = text.find("]);", start)
    entries = _ENTRY.findall(text[start:end])
    if not entries:
        raise SystemExit(
            f"patchorder: `KNOWN_DOUBLE_PATCHES` in {path} parsed to zero "
            f"entries. Refusing: an empty allowlist makes every check vacuous."
        )
    return entries


def _balanced(src: str, start: int) -> tuple[str | None, int]:
    pairs = {"{": "}", "[": "]", "(": ")"}
    open_ch = src[start]
    close_ch = pairs[open_ch]
    depth, i, in_str, n = 0, start, None, len(src)
    while i < n:
        c = src[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
        elif c in "\"'`":
            in_str = c
        elif c == "/" and src[i : i + 2] == "//":
            nl = src.find("\n", i)
            if nl < 0:
                break
            i = nl
            continue
        elif c == "/" and src[i : i + 2] == "/*":
            i = src.find("*/", i) + 2
            continue
        elif c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return src[start : i + 1], i + 1
        i += 1
    return None, n


def top_level_keys(obj_src: str) -> set[str]:
    body = obj_src[1:-1]
    keys: list[str] = []
    line: list[str] = []
    i, in_str = 0, None
    while i < len(body):
        c = body[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
            line.append(c)
            i += 1
            continue
        if c in "\"'`":
            in_str = c
            line.append(c)
            i += 1
            continue
        if c == "/" and body[i : i + 2] == "//":
            nl = body.find("\n", i)
            i = len(body) if nl < 0 else nl
            continue
        if c == "/" and body[i : i + 2] == "/*":
            i = body.find("*/", i) + 2
            continue
        if c in "{[(":
            seg = "".join(line) + c
            found = _KEY.findall(seg)
            if found:
                keys.append(found[-1].strip("[]"))
            _, i = _balanced(body, i)
            line = []
            continue
        if c == ",":
            keys += [m.group(1).strip("[]") for m in _KEY.finditer("".join(line))]
            line = []
            i += 1
            continue
        line.append(c)
        i += 1
    keys += [m.group(1).strip("[]") for m in _KEY.finditer("".join(line))]
    return {k for k in keys if k and not k[0].isdigit()}


def addon_of(path: Path) -> str:
    parts = path.parts
    for i, p in enumerate(parts):
        if p == "static" and i:
            return parts[i - 1]
    return path.parent.name


def build_index(roots) -> tuple[dict[str, set[str]], dict[str, set[str]], list]:
    index: dict[str, set[str]] = defaultdict(set)
    sites: dict[str, set[str]] = defaultdict(set)
    unresolved: list[tuple[str, str, str]] = []
    for root in roots:
        for f in sorted(Path(root).rglob("*.js")):
            s = str(f)
            if "/static/" not in s:
                continue
            try:
                src = f.read_text(errors="replace")
            except OSError:
                continue
            if "patch(" not in src:
                continue
            addon = addon_of(f)
            consts = {}
            for m in _CONST_OBJ.finditer(src):
                obj, _ = _balanced(src, m.end() - 1)
                if obj:
                    consts[m.group(1)] = obj
            for m in _PATCH_CALL.finditer(src):
                depth, j, arg = 0, m.end(), []
                while j < len(src):
                    c = src[j]
                    if c in "([{":
                        depth += 1
                    elif c in ")]}":
                        if depth == 0:
                            break
                        depth -= 1
                    elif c == "," and depth == 0:
                        break
                    arg.append(c)
                    j += 1
                target = "".join(arg).strip()
                if not target or src[j : j + 1] != ",":
                    continue
                k = j + 1
                while k < len(src) and src[k] in " \t\r\n":
                    k += 1
                if src[k : k + 1] == "{":
                    obj, _ = _balanced(src, k)
                else:
                    ident = re.match(r"[A-Za-z_$][\w$]*", src[k:])
                    obj = consts.get(ident.group(0)) if ident else None
                    if obj is None:
                        unresolved.append((s, target, src[k : k + 60].split("\n")[0]))
                        continue
                if obj is None:
                    continue
                for key in top_level_keys(obj):
                    pair = f"{target} :: {key}"
                    index[pair].add(addon)
                    sites[pair].add(s)
    return index, sites, unresolved


def default_roots(odoo_root: Path) -> list[Path]:
    roots = [odoo_root / "addons", odoo_root / "odoo" / "addons"]
    workspace = find_workspace(odoo_root)
    if workspace:
        roots += sibling_repo_paths(ROOT)
    return [r for r in roots if r.is_dir()]


def sweep(allowlist, sites):
    return [
        (pair, sorted(sites.get(pair, ())))
        for pair in allowlist
        if len(sites.get(pair, ())) < MIN_SITES
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=_DESCRIPTION)
    parser.add_argument(
        "roots",
        nargs="*",
        type=Path,
        help="addons roots to scan (default: the whole workspace)",
    )
    parser.add_argument(
        "--check", action="store_true", help="exit 1 if any allowlist entry is stale"
    )
    parser.add_argument("--json", action="store_true", help="machine-readable")
    args = parser.parse_args()

    odoo_root = ROOT
    roots = args.roots or default_roots(odoo_root)
    if not roots:
        raise SystemExit("patchorder: no addons root to scan. Refusing.")

    allowlist = read_allowlist(odoo_root / ALLOWLIST_REL)
    index, sites, unresolved = build_index(roots)

    if not sites:
        raise SystemExit(
            f"patchorder: scanned {len(roots)} root(s) and found no `patch()` "
            f"call at all. The roots are wrong or the scan is broken; refusing "
            f"to report {len(allowlist)} stale entries on that basis."
        )

    stale = sweep(allowlist, sites)
    scanned = [str(r) for r in roots]

    seen = {r.resolve() for r in roots}
    unscanned = [r for r in default_roots(odoo_root) if r.resolve() not in seen]

    if args.json:
        print(
            json.dumps(
                {
                    "roots": scanned,
                    "unscanned_roots": [str(r) for r in unscanned],
                    "scope_complete": not unscanned,
                    "allowlist": len(allowlist),
                    "indexed_pairs": len(index),
                    "unresolved_call_sites": len(unresolved),
                    "stale": [{"pair": p, "sites": s} for p, s in stale],
                },
                indent=2,
            )
        )
    else:
        print(f"roots scanned      : {len(roots)}")
        for r in scanned:
            print(f"  {r}")
        print(f"allowlist entries  : {len(allowlist)}")
        print(f"pairs indexed      : {len(index)}")
        print(
            f"unresolved sites   : {len(unresolved)}  "
            f"(patch(X, factory()) and similar — not object literals)"
        )
        if unscanned:
            print("\nSCOPE INCOMPLETE — these roots exist but were not scanned:")
            for r in unscanned:
                print(f"  {r}")
            print(
                "Anything below is a CANDIDATE only: an entry whose second "
                "patcher lives in an\nunscanned root is indistinguishable here "
                "from one whose patch was removed."
            )
        if stale:
            print(
                f"\n{'CANDIDATES' if unscanned else 'STALE'} ({len(stale)}) — "
                f"fewer than {MIN_SITES} patch sites in the scanned roots:"
            )
            for pair, s in stale:
                print(f"  {pair}")
                for one in s:
                    print(f"      {one}")
                if not s:
                    print("      (no patch site found anywhere)")
            if unscanned:
                print("\nRe-run over the whole workspace before pruning anything.")
            else:
                print(
                    "\nPrune these from KNOWN_DOUBLE_PATCHES. Removing an entry "
                    "only makes the audit stricter:\nif a second patcher later "
                    "appears, its assertion fires and demands review."
                )
        else:
            print(
                f"\nno stale entries — every allowlist pair still has "
                f">= {MIN_SITES} patch sites"
            )

    if args.check and unscanned:
        print(
            "patchorder: --check refused, scope incomplete (see above). A verdict "
            "needs every addons root.",
            file=sys.stderr,
        )
        return 2
    return 1 if (stale and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())
