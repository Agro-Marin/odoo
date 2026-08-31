"""A `Pick<>` on a context bag must name exactly what the file reaches.

`ListRenderer` hands its collaborators one `ListGridContext`: 27 getters and
callbacks covering selection, keyboard nav, virtualization, aggregates and
column state. Passing the whole bag to each of them would make every consumer
look coupled to all 27, and nothing would say which four a hook actually needs.

Each consumer therefore narrows its parameter:

    @param {Pick<import("./list_renderer").ListGridContext,
     "getColumns" | "getFields">} ctx

That annotation is the coupling report. It is only worth reading while it is
exact, and it drifts in both directions for different reasons:

  - reaching a member the `Pick<>` omits is caught by tsc, but only as one more
    error inside a project-wide count of ~1500 that names no file;
  - declaring a member the file never reaches is invisible to tsc entirely --
    an unused property in a `Pick<>` is legal -- so a consumer keeps claiming a
    dependency it dropped, and the report overstates the coupling forever.

The second is the one that rots quietly, which is why this gate exists. Both
directions fail here, and the finding names the file and the member.

ADR-0022 is the record: an object that crosses a boundary by value is an
interface, and is declared and pinned like one. It named three such objects --
archInfo, env.config, the field record -- each with its own pin. `ListGridContext`
is a fourth, and `Pick<>` is already the declaration its consumers write; this is
the gate that makes tree and declaration disagree fail.

Drift-zero: there is no baseline count. The seven narrowed parameters were exact
when this landed, and the gate keeps them that way.
"""

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _repo_root import find_odoo_root

ADR = "0022"

ROOT = find_odoo_root(Path(__file__).resolve(), tool="js_context_narrowing")
WEB_STATIC = ROOT / "addons" / "web" / "static"

# A narrowed parameter is written three ways, and all three must be understood
# or the gate quietly covers only the easy files:
#
#   @param {Pick<import("./x").Ctx, "a" | "b">} ctx        inline
#   @param {ListEditContext} ctx                           a typedef'd Pick
#   @param {Pick<...> & import("./y").ListEditContext} ctx an intersection of both
#
# So: collect every `@typedef {Pick<...>} Name` in the tree first, then resolve a
# parameter's type expression against that registry.
PARAM_HEAD = re.compile(r"@param\s*\{")
TYPEDEF = re.compile(r"@typedef\s*\{")
TYPEDEF_NAME = re.compile(r"^\s*([\w$.]+)")
TYPE_REF = re.compile(r'import\(\s*"(?P<module>[^"]+)"\s*\)\s*\.\s*(?P<name>\w+)')
BARE_REF = re.compile(r"(?<![\w$.\"])([A-Z]\w+)")
PICK_BODY = re.compile(r"Pick\s*<", re.DOTALL)
MEMBER = re.compile(r'"(\w+)"')


def _balanced(text: str, start: int, open_ch: str, close_ch: str) -> tuple[str, int]:
    """The substring inside the delimiters opening at `start`, and the index after."""
    depth = 0
    i = start
    while i < len(text):
        if text[i] == open_ch:
            depth += 1
        elif text[i] == close_ch:
            depth -= 1
            if depth == 0:
                return text[start + 1 : i], i + 1
        i += 1
    return "", len(text)


def _strip_jsdoc_stars(text: str) -> str:
    return re.sub(r"\n\s*\*", "\n", text)


def _split_top_level(body: str) -> tuple[str, bool, str]:
    """Split a `Pick<>` body at its top-level comma."""
    depth = 0
    for i, ch in enumerate(body):
        if ch in "<[({":
            depth += 1
        elif ch in ">])}":
            depth -= 1
        elif ch == "," and depth == 0:
            return body[:i], True, body[i + 1 :]
    return body, False, ""


@dataclass(frozen=True)
class Finding:
    contract: str
    path: str
    detail: str

    def __str__(self) -> str:
        return f"  {self.path:44s} {self.detail}"


def _strip_comments(source: str) -> str:
    """Drop comments so a member named only in prose does not count as a reach."""
    out = []
    i, n = 0, len(source)
    while i < n:
        two = source[i : i + 2]
        if two == "/*":
            end = source.find("*/", i + 2)
            i = n if end == -1 else end + 2
        elif two == "//":
            end = source.find("\n", i)
            i = n if end == -1 else end
        elif source[i] in "\"'`":
            quote = source[i]
            i += 1
            while i < n and source[i] != quote:
                i += 2 if source[i] == "\\" else 1
            i += 1
        else:
            out.append(source[i])
            i += 1
    return "".join(out)


def reached_members(code: str, param: str) -> set[str]:
    """Members of `param` the code actually touches.

    Three forms carry a reach: a direct `ctx.member`, the same behind a field
    the constructor stored (`this.ctx.member`), and a destructure of the whole
    parameter. Anything else -- a computed `ctx["member"]`, or forwarding the
    bag to a function this file cannot see -- is reported rather than guessed
    at, because a gate that silently under-counts is worse than none.
    """
    members = set()
    members.update(
        match.group(1)
        for match in re.finditer(rf"(?<![\w$.]){re.escape(param)}\s*\.\s*(\w+)", code)
    )
    members.update(
        match.group(1)
        for match in re.finditer(rf"this\s*\.\s*{re.escape(param)}\s*\.\s*(\w+)", code)
    )
    for match in re.finditer(
        rf"\{{([^{{}}]*)\}}\s*=\s*(?:this\s*\.\s*)?{re.escape(param)}\b", code
    ):
        for part in match.group(1).split(","):
            name = part.split(":")[0].strip()
            if name.isidentifier():
                members.add(name)
    return members


def opaque_uses(code: str, param: str) -> list[str]:
    """Uses this gate cannot resolve, and so must not silently pass."""
    reasons = []
    if re.search(rf"(?<![\w$.]){re.escape(param)}\s*\[", code):
        reasons.append("computed access")
    return reasons


def _annotations(source: str, marker: re.Pattern) -> list[tuple[str, str]]:
    """(type expression, trailing name) for each `@param {…} name` / `@typedef {…} Name`.

    `@param {T} params.action` types a property of a parameter, not a parameter,
    so its name is dotted and it is not a narrowed context bag; those are
    dropped rather than attributed to `params`.
    """
    out = []
    for head in marker.finditer(source):
        brace = source.index("{", head.start())
        expr, after = _balanced(source, brace, "{", "}")
        tail = TYPEDEF_NAME.match(_strip_jsdoc_stars(source[after : after + 80]))
        name = tail.group(1) if tail else ""
        if "." in name:
            continue
        out.append((_strip_jsdoc_stars(expr), name))
    return out


def typedef_registry(src: Path) -> dict[tuple[str, str], str]:
    """Every `@typedef {…} Name`, keyed by (module path relative to src, name)."""
    registry: dict[tuple[str, str], str] = {}
    for path in sorted(src.rglob("*.js")):
        source = path.read_text(encoding="utf8", errors="replace")
        if "@typedef" not in source:
            continue
        rel = path.relative_to(src).as_posix()
        for expr, name in _annotations(source, TYPEDEF):
            if name:
                registry[(rel, name)] = expr
    return registry


def _resolve_module(spec: str, from_rel: str) -> str:
    if spec.startswith("@web/"):
        target = spec[len("@web/") :]
    elif spec.startswith("."):
        target = (Path(from_rel).parent / spec).as_posix()
        while "/./" in target:
            target = target.replace("/./", "/")
        parts: list[str] = []
        for part in target.split("/"):
            if part == "..":
                if parts:
                    parts.pop()
            elif part not in (".", ""):
                parts.append(part)
        target = "/".join(parts)
    else:
        return ""
    return target if target.endswith(".js") else target + ".js"


def declared_members(
    expr: str,
    from_rel: str,
    registry: dict[tuple[str, str], str],
    depth: int = 0,
) -> tuple[set[str], set[str]]:
    """Members a type expression narrows to, and the context names it draws from.

    Handles the inline `Pick<>`, a reference to a typedef'd one (same file or
    imported), and any intersection of those.
    """
    members: set[str] = set()
    contexts: set[str] = set()
    if depth > 4:
        return members, contexts
    for pick in PICK_BODY.finditer(expr):
        body, _ = _balanced(expr, expr.index("<", pick.start()), "<", ">")
        # Pick<Source, "a" | "b">: only the second operand names members. Taking
        # every quoted string would read the index in `Factories["action"]` as
        # a member of the thing being narrowed.
        source_type, _, picked = _split_top_level(body)
        members.update(MEMBER.findall(picked))
        ref = TYPE_REF.search(source_type)
        if ref:
            contexts.add(ref.group("name"))
        else:
            bare = BARE_REF.search(source_type)
            if bare:
                contexts.add(bare.group(1))
    # Only follow a named type when it is itself a narrowing. Following any
    # capitalised name pulls unrelated typedefs in and invents members the file
    # was never asked to reach.
    for ref in TYPE_REF.finditer(expr):
        target = _resolve_module(ref.group("module"), from_rel)
        nested = registry.get((target, ref.group("name")))
        if nested and "Pick<" in nested:
            sub_members, sub_contexts = declared_members(
                nested, target, registry, depth + 1
            )
            members |= sub_members
            contexts |= sub_contexts
    stripped = TYPE_REF.sub("", expr)
    for bare in BARE_REF.finditer(stripped):
        nested = registry.get((from_rel, bare.group(1)))
        if nested and "Pick<" in nested:
            sub_members, sub_contexts = declared_members(
                nested, from_rel, registry, depth + 1
            )
            members |= sub_members
            contexts |= sub_contexts
    return members, contexts


IMPORT_NAMES = re.compile(
    r"import\s*\{(?P<names>[^}]*)\}\s*from\s*\"(?P<module>[^\"]+)\""
)
FUNC_AFTER_DOC = re.compile(r"\A\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)")


def narrowed_functions(
    src: Path, registry: dict[tuple[str, str], str]
) -> dict[tuple[str, str], set[str]]:
    """(module, function name) -> members its narrowed parameters declare.

    A hook that forwards its whole context to a collaborator -- as
    useListKeyboardNavigation hands `ctx` to makeEditHandlers -- reaches every
    member the collaborator declares. Without this the forwarded half reads as
    over-declared, and the honest intersection its author wrote would fail.
    """
    out: dict[tuple[str, str], set[str]] = {}
    for path in sorted(src.rglob("*.js")):
        source = path.read_text(encoding="utf8", errors="replace")
        if "Pick<" not in source:
            continue
        rel = path.relative_to(src).as_posix()
        for block in re.finditer(r"/\*\*(?P<doc>.*?)\*/", source, re.DOTALL):
            head = FUNC_AFTER_DOC.match(source[block.end() :])
            if not head:
                continue
            members: set[str] = set()
            for expr, param in _annotations(block.group("doc"), PARAM_HEAD):
                if param:
                    members |= declared_members(expr, rel, registry)[0]
            if members:
                out[(rel, head.group(1))] = members
    return out


def forwarded_members(
    code: str,
    source: str,
    param: str,
    from_rel: str,
    functions: dict[tuple[str, str], set[str]],
) -> set[str]:
    """Members reached by whatever this file hands `param` to."""
    origin = {}
    for imp in IMPORT_NAMES.finditer(source):
        target = _resolve_module(imp.group("module"), from_rel)
        for name in imp.group("names").split(","):
            name = name.split(" as ")[-1].strip()
            if name:
                origin[name] = target
    # A function's own declaration -- `function useThing(ctx)` -- has the shape
    # of a call passing `ctx`. Skip those, or every narrowed function reads as
    # forwarding to itself and nothing is ever over-declared.
    declarations = {m.start(1) for m in re.finditer(r"function\s+(\w+)\s*\(", code)}
    members: set[str] = set()
    for call in re.finditer(rf"(\w+)\s*\(([^()]*?)\b{re.escape(param)}\b\s*[,)]", code):
        if call.start(1) in declarations:
            continue
        callee = call.group(1)
        for key in ((origin.get(callee, ""), callee), (from_rel, callee)):
            if key in functions:
                members |= functions[key]
    return members


def analyse(web_static: Path) -> list[Finding]:
    findings: list[Finding] = []
    src = web_static / "src"
    registry = typedef_registry(src)
    functions = narrowed_functions(src, registry)
    for path in sorted(src.rglob("*.js")):
        source = path.read_text(encoding="utf8", errors="replace")
        rel_src = path.relative_to(src).as_posix()
        rel = path.relative_to(web_static).as_posix()
        code = _strip_comments(source)
        # One parameter name may be annotated at several sites in a file (a hook
        # and the class it builds); the file's declaration is their union, and
        # the reaches are the file's.
        declared: dict[str, set[str]] = {}
        context_of: dict[str, set[str]] = {}
        for expr, param in _annotations(source, PARAM_HEAD):
            if not param:
                continue
            members, contexts = declared_members(expr, rel_src, registry)
            if not members:
                continue
            declared.setdefault(param, set()).update(members)
            context_of.setdefault(param, set()).update(contexts)
        for param, names in declared.items():
            context = "/".join(sorted(context_of[param])) or "context"
            findings.extend(
                Finding(
                    "unresolvable",
                    rel,
                    f"`{param}` uses {reason}; this gate cannot verify the "
                    f"{context} narrowing",
                )
                for reason in opaque_uses(code, param)
            )
            reached = reached_members(code, param) | forwarded_members(
                code, source, param, rel_src, functions
            )
            findings.extend(
                Finding(
                    "over-declared",
                    rel,
                    f"`{param}` declares {context}.{name} and never reaches "
                    f"it — drop it from the Pick<>",
                )
                for name in sorted(names - reached)
            )
            findings.extend(
                Finding(
                    "under-declared",
                    rel,
                    f"`{param}` reaches {context}.{name}, which its Pick<> "
                    f"omits — add it",
                )
                for name in sorted(reached - names)
            )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="exit 1 on findings")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--table", action="store_true", help="print every narrowed parameter"
    )
    parser.add_argument("--web-static", type=Path, default=WEB_STATIC)
    args = parser.parse_args(argv)

    src = args.web_static / "src"
    scanned = sum(1 for _ in src.rglob("*.js")) if src.is_dir() else 0
    if not scanned:
        parser.error(f"no JS sources under {src} — the scan reached nothing")

    findings = analyse(args.web_static)

    if args.json:
        print(json.dumps({"findings": [asdict(f) for f in findings]}, indent=2))
        return 1 if (findings and args.check) else 0

    print("JS context-narrowing check (drift-zero)")
    print("=" * 72)
    if args.table:
        registry = typedef_registry(src)
        functions = narrowed_functions(src, registry)
        for path in sorted(src.rglob("*.js")):
            source = path.read_text(encoding="utf8", errors="replace")
            rel_src = path.relative_to(src).as_posix()
            code = _strip_comments(source)
            for expr, param in _annotations(source, PARAM_HEAD):
                if not param:
                    continue
                names, _ = declared_members(expr, rel_src, registry)
                if not names:
                    continue
                print(
                    f"  {path.relative_to(args.web_static).as_posix():44s} "
                    f"{param}: {len(names):2d} declared, "
                    f"{len(reached_members(code, param) | forwarded_members(code, source, param, rel_src, functions)):2d} reached"
                )
        print("-" * 72)
    for contract in ("over-declared", "under-declared", "unresolvable"):
        hits = [f for f in findings if f.contract == contract]
        print(f"[{'FAIL' if hits else '  ok'}] {contract}: {len(hits)}")
        for f in hits:
            print(f)
    print("-" * 72)
    if not findings:
        print("\nEvery Pick<> names exactly what its file reaches. ✓")

    return 1 if (findings and args.check) else 0


if __name__ == "__main__":
    sys.exit(main())
