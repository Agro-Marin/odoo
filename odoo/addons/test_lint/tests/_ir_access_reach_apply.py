"""Write a reach plan (`_ir_access_reach_sources.py`) into the modules.

    python _ir_access_reach_apply.py <plan.json> [--dry-run]

Rows: a converted CSV row gets its `reach` and `anchor` and keeps only its
fixed filter as `domain`; a split permission becomes `<id>`, `<id>_2`, ... in
place. XML records are rewritten field by field and never split (a split XML
row keeps its domain). Anchors: each module declares the keys its own rows
read, on its class of the model when it has one, else on an `_inherit` stub in
`models/access_anchors.py`.
"""

import argparse
import ast
import csv
import io
import json
import re
from collections import defaultdict
from pathlib import Path

HEADER_AFTER = "operation"
NEW_COLUMNS = ("reach", "anchor")
PREDICATE_COLUMNS = ("predicate_id/id", "predicate_args")
# the record each predicate the recognizer names is shipped as
PREDICATE_XMLIDS = {
    "base.user_has_access": "base.access_predicate_user_has_access",
    "base.is_member": "base.access_predicate_is_member",
    "mail.follows": "mail.access_predicate_follows",
}


def predicate_args(part: dict) -> str:
    return json.dumps(dict(part.get("args") or ()), sort_keys=True)


def csv_rewrite(path: Path, rows: dict[str, dict]) -> int:
    text = path.read_text(encoding="utf-8")
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    records = list(reader)
    if not any(r and r[0] in rows for r in records):
        return 0
    if "reach" not in header:
        at = header.index(HEADER_AFTER) + 1
        header[at:at] = list(NEW_COLUMNS)
        records = [r[:at] + ["", ""] + r[at:] if r else r for r in records]
    named = any(
        part["reach"] == "predicate" for row in rows.values() for part in row["parts"]
    )
    if named and PREDICATE_COLUMNS[0] not in header:
        at = header.index("anchor") + 1
        header[at:at] = list(PREDICATE_COLUMNS)
        records = [r[:at] + ["", ""] + r[at:] if r else r for r in records]
    i_id, i_name = header.index("id"), header.index("name")
    i_reach, i_anchor, i_domain = (
        header.index("reach"),
        header.index("anchor"),
        header.index("domain"),
    )
    out, changed = [], 0
    for record in records:
        if not record or record[0] not in rows:
            out.append(record)
            continue
        parts = rows[record[0]]["parts"]
        for index, part in enumerate(parts, start=1):
            new = list(record)
            if index > 1:
                new[i_id] = f"{record[i_id]}_{index}"
                new[i_name] = f"{record[i_name]} ({index})"
            new[i_reach] = part["reach"]
            new[i_anchor] = part.get("anchor", "")
            new[i_domain] = part["static"]
            if PREDICATE_COLUMNS[0] in header:
                i_predicate = header.index(PREDICATE_COLUMNS[0])
                i_args = header.index(PREDICATE_COLUMNS[1])
                named = part["reach"] == "predicate"
                new[i_predicate] = PREDICATE_XMLIDS[part["predicate"]] if named else ""
                new[i_args] = predicate_args(part) if named else ""
            out.append(new)
        changed += 1
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(out)
    path.write_text(buffer.getvalue(), encoding="utf-8")
    return changed


def xml_rewrite(path: Path, rows: dict[str, dict]) -> int:
    # one field line per value, keeping the file's own formatting elsewhere
    text = path.read_text(encoding="utf-8")
    changed = 0
    for xmlid, row in rows.items():
        if len(row["parts"]) != 1:
            continue
        part = row["parts"][0]
        start = re.search(
            rf'<record\s+id="{re.escape(xmlid)}"\s+model="ir\.access"\s*>', text
        )
        if not start:
            continue
        end = text.index("</record>", start.end())
        body = text[start.end() : end]
        indent = re.search(r"\n(\s*)<field", body).group(1)
        body = re.sub(
            r'\s*<field\s+name="domain"(?:\s[^>]*)?(?<!/)>.*?</field>',
            "",
            body,
            flags=re.DOTALL,
        )
        body = re.sub(r'\s*<field\s+name="domain"\s[^>]*/>', "", body)
        body = re.sub(
            r'\s*<field\s+name="(reach|anchor|predicate_id|predicate_args)"'
            r"(?:\s[^>]*)?(?:/>|(?<!/)>.*?</field>)",
            "",
            body,
            flags=re.DOTALL,
        )
        added = (
            f'\n{indent}<field name="reach">{part["reach"]}</field>'
            if part["reach"]
            else f'\n{indent}<field name="reach" eval="False" />'
        )
        if part["reach"] == "predicate":
            added += (
                f'\n{indent}<field name="predicate_id" '
                f'ref="{PREDICATE_XMLIDS[part["predicate"]]}" />'
                f'\n{indent}<field name="predicate_args" '
                f'eval="{dict(part.get("args") or ())!r}" />'
            )
        if part.get("anchor"):
            added += f'\n{indent}<field name="anchor">{part["anchor"]}</field>'
        if part["static"]:
            static = part["static"].replace("&", "&amp;").replace("<", "&lt;")
            added += f'\n{indent}<field name="domain">{static}</field>'
        else:
            added += f'\n{indent}<field name="domain" eval="False" />'
        body = body.rstrip() + added + "\n" + indent[:-4]
        text = text[: start.end()] + body + text[end:]
        changed += 1
    if changed:
        path.write_text(text, encoding="utf-8")
    return changed


def model_classes(module: Path) -> dict[str, tuple[Path, ast.ClassDef]]:
    # the class a module defines or extends each model with, when one class
    # names exactly that model
    found: dict[str, tuple[Path, ast.ClassDef]] = {}
    for path in sorted(module.rglob("*.py")):
        if {"tests", "migrations", "upgrades", "static"} & set(
            path.relative_to(module).parts
        ):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            name, inherits = None, []
            for stmt in node.body:
                if not (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1):
                    continue
                target = stmt.targets[0]
                if not isinstance(target, ast.Name):
                    continue
                values = (
                    [stmt.value]
                    if isinstance(stmt.value, ast.Constant)
                    else list(getattr(stmt.value, "elts", []))
                )
                strings = [
                    v.value
                    for v in values
                    if isinstance(v, ast.Constant) and isinstance(v.value, str)
                ]
                if target.id == "_name" and strings:
                    name = strings[0]
                elif target.id == "_inherit":
                    inherits = strings
            model = name or (inherits[0] if len(inherits) == 1 else None)
            if model:
                found.setdefault(model, (path, node))
    return found


def render(anchors: dict[str, str], indent: str) -> str:
    inner = "".join(
        f'{indent}        "{key}": {value},\n' for key, value in sorted(anchors.items())
    )
    return f"{indent}_access_anchors = frozendict(\n{indent}    {{\n{inner}{indent}    }}\n{indent})\n"


def declare_in_class(path: Path, node: ast.ClassDef, anchors: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    existing = None
    for stmt in node.body:
        if (
            isinstance(stmt, ast.Assign)
            and isinstance(stmt.targets[0], ast.Name)
            and stmt.targets[0].id == "_access_anchors"
        ):
            existing = stmt
    indent = " " * node.body[0].col_offset
    if existing is not None:
        old = ast.get_source_segment("".join(lines), existing.value)
        value = (
            existing.value.args[0]
            if isinstance(existing.value, ast.Call)
            else existing.value
        )
        merged = {
            ast.literal_eval(k): ast.get_source_segment("".join(lines), v)
            for k, v in zip(value.keys, value.values, strict=True)
        }
        merged.update(anchors)
        del old
        start, end = existing.lineno - 1, existing.end_lineno
        lines[start:end] = [render(merged, indent)]
    else:
        # after the leading class attributes (_name, _inherit, _description...)
        last = node.body[0]
        for stmt in node.body:
            if (
                isinstance(stmt, (ast.Assign, ast.AnnAssign))
                and isinstance(
                    getattr(stmt, "targets", [getattr(stmt, "target", None)])[0],
                    ast.Name,
                )
                and getattr(stmt, "targets", [getattr(stmt, "target", None)])[
                    0
                ].id.startswith("_")
            ):
                last = stmt
            elif not isinstance(stmt, ast.Expr):
                break
        lines[last.end_lineno : last.end_lineno] = [render(anchors, indent)]
    text = "".join(lines)
    text = ensure_imports(text)
    path.write_text(text, encoding="utf-8")


def ensure_imports(text: str) -> str:
    if not re.search(
        r"^from odoo(\.tools)? import .*\bfrozendict\b", text, re.MULTILINE
    ):
        text = re.sub(
            r"^(from odoo import [^\n]+\n)",
            r"\1from odoo.tools import frozendict\n",
            text,
            count=1,
            flags=re.MULTILINE,
        )
    if "models.Anchor" in text and not re.search(
        r"^from odoo import .*\bmodels\b", text, re.MULTILINE
    ):
        text = "from odoo import models\n" + text
    return text


BASES = {
    "Model": "Model",
    "TransientModel": "TransientModel",
    "AbstractModel": "AbstractModel",
}
_KINDS: dict[str, str] = {}


def model_base(roots: list[Path], model: str) -> str:
    # the base the model is defined with, read from its defining class
    if not _KINDS:
        pattern = re.compile(
            r"^class \w+\((?:models\.)?(Model|TransientModel|AbstractModel)\):"
            r"(?:(?!^class ).)*?^\s+_name\s*=\s*[\"']([\w.]+)[\"']",
            re.MULTILINE | re.DOTALL,
        )
        for root in roots:
            for path in root.rglob("*.py"):
                if "tests" in path.parts or "migrations" in path.parts:
                    continue
                for base, name in pattern.findall(path.read_text(encoding="utf-8")):
                    _KINDS.setdefault(name, base)
    return BASES[_KINDS.get(model, "Model")]


ROOTS: list[Path] = []


def declare_in_stub(module: Path, model: str, anchors: dict[str, str]) -> None:
    models_dir = module / "models"
    stub = models_dir / "access_anchors.py"
    if not models_dir.is_dir():
        models_dir.mkdir()
        (models_dir / "__init__.py").write_text("", encoding="utf-8")
        init = module / "__init__.py"
        init.write_text(init.read_text(encoding="utf-8") + "from . import models\n")
    if not stub.exists():
        stub.write_text(
            "from odoo import models\nfrom odoo.tools import frozendict\n",
            encoding="utf-8",
        )
        init = models_dir / "__init__.py"
        init.write_text(
            init.read_text(encoding="utf-8") + "from . import access_anchors\n"
        )
    class_name = "".join(part.capitalize() for part in re.split(r"[._]", model))
    stub.write_text(
        stub.read_text(encoding="utf-8")
        + f"\n\nclass {class_name}(models.{model_base(ROOTS, model)}):\n"
        + f'    _inherit = "{model}"\n\n'
        + render(anchors, "    ")
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--roots", default="odoo-s1/odoo/addons:odoo-s1/addons:enterprise:agromarin"
    )
    args = parser.parse_args()
    ROOTS.extend(Path(root) for root in args.roots.split(":"))
    data = json.loads(args.plan.read_text(encoding="utf-8"))
    declarations = data["declarations"]
    by_file: dict[str, dict[str, dict]] = defaultdict(dict)
    needed: dict[tuple[str, str], set[str]] = defaultdict(set)
    modules: dict[str, Path] = {}
    for row in data["rows"]:
        if not row["parts"]:
            continue
        model = row["model"]
        keys = {p["anchor"] for p in row["parts"] if p.get("anchor")}
        keys |= {
            {
                "own": "owner",
                "team": "team",
                "company": "company",
                "partner": "partner",
            }[p["reach"]]
            for p in row["parts"]
            if p["reach"] in ("own", "team", "company", "partner")
            and not p.get("anchor")
        }
        declared = {k for k in keys if k in declarations.get(model, {})}
        if not all("anchor" in p for p in row["parts"]):
            # the planner found no anchor for a part: the row keeps its domain
            continue
        by_file[row["file"]][row["xmlid"]] = row
        file = Path(row["file"])
        module = (
            file.parent.parent if file.parent.name == "security" else file.parents[1]
        )
        modules[row["module"]] = module
        for key in declared:
            needed[(row["module"], model)].add(key)
    rows_changed = 0
    for file, rows in sorted(by_file.items()):
        path = Path(file)
        if args.dry_run:
            rows_changed += len(rows)
            continue
        rows_changed += (
            csv_rewrite(path, rows)
            if path.suffix == ".csv"
            else xml_rewrite(path, rows)
        )
    declared_count = 0
    for (module_name, model), keys in sorted(needed.items()):
        anchors = {key: declarations[model][key] for key in keys}
        declared_count += len(anchors)
        if args.dry_run:
            continue
        module = modules[module_name]
        # re-read each time: an earlier declaration moved the lines
        classes = model_classes(module)
        if model in classes:
            declare_in_class(*classes[model], anchors)
        else:
            declare_in_stub(module, model, anchors)
    print(
        json.dumps(
            {
                "rows": rows_changed,
                "declarations": declared_count,
                "modules": len({m for m, _ in needed}),
            }
        )
    )


if __name__ == "__main__":
    main()
