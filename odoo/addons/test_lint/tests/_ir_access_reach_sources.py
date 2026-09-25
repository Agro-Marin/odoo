"""Rewrite the shipped ir.access rows as reaches through anchors (P4 S2).

Run in an odoo shell on a database whose registry holds the models the rows
name (their anchors and fields are read from it, never from source):

    odoo-bin shell -d <db> < _ir_access_reach_sources.py   # plan, as JSON
    REACH_APPLY=1 odoo-bin shell -d <db> < ...             # and write it

A row converts only when `ir_access_reach.proves` finds the proposed rows equal
to its domain; anything else keeps its domain and counts against the floor.
"""

import ast
import csv
import io
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

from lxml import etree

from odoo.orm.models.anchors import (
    ANCHOR_KINDS,
    Anchor,
    infer_company_variant,
)

from odoo.addons.base.models.ir_access import REACH_ANCHOR
from odoo.addons.base.models.ir_access_reach import Part, propose, proves

ROOTS = [
    Path(p)
    for p in os.environ.get(
        "REACH_ROOTS",
        "odoo/odoo/addons:odoo/addons:enterprise:agromarin",
    ).split(":")
]
OUT = Path(os.environ.get("REACH_OUT", "/tmp/reach_plan.json"))
SKIP_DIRS = {"static", "node_modules", "migrations", "upgrades", "tests"}
KIND_OF_RUNG = {
    ("own", "owner"): "owner",
    ("own", "creator"): "creator",
    ("own", "employee"): "employee",
    ("own", "partner"): "partner",
    ("partner", "partner"): "partner",
    ("team", "team"): "team",
    ("company", "company"): "company",
}


def env_():
    return globals()["env"]


def module_rows():
    # every ir.access row a module ships: (module, file, xmlid, values)
    for root in ROOTS:
        for manifest in sorted(root.glob("*/__manifest__.py")):
            module = manifest.parent
            if module.name.startswith("test_"):
                continue
            csv_path = module / "security/ir.access.csv"
            if csv_path.exists():
                reader = csv.DictReader(
                    io.StringIO(csv_path.read_text(encoding="utf-8"))
                )
                for values in reader:
                    yield (
                        module,
                        csv_path,
                        values.get("id"),
                        {
                            "model": values.get("model_id/id"),
                            "kind": values.get("kind"),
                            "domain": (values.get("domain") or "").strip(),
                            "reach": values.get("reach"),
                        },
                        {
                            row.get("id")
                            for row in csv.DictReader(
                                io.StringIO(csv_path.read_text(encoding="utf-8"))
                            )
                        },
                    )
            for xml_path in sorted(module.rglob("*.xml")):
                if SKIP_DIRS & set(xml_path.relative_to(module).parts):
                    continue
                text = xml_path.read_bytes()
                if b'"ir.access"' not in text:
                    continue
                tree = etree.fromstring(text)
                for record in tree.iter("record"):
                    if record.get("model") != "ir.access":
                        continue
                    values = {}
                    for fld in record.iter("field"):
                        values[fld.get("name")] = (
                            fld.get("ref") or fld.get("eval") or (fld.text or "")
                        ).strip()
                    if "model_id" not in values or "kind" not in values:
                        continue
                    yield (
                        module,
                        xml_path,
                        record.get("id"),
                        {
                            "model": values["model_id"],
                            "kind": values["kind"],
                            "domain": values.get("domain", ""),
                            "reach": values.get("reach"),
                        },
                        {r.get("id") for r in tree.iter("record")},
                    )


def model_name(module: str, ref: str | None) -> str | None:
    if not ref:
        return None
    ref = ref if "." in ref else f"{module}.{ref}"
    data = (
        env_()["ir.model.data"]
        .sudo()
        .search(
            [
                ("module", "=", ref.split(".", 1)[0]),
                ("name", "=", ref.split(".", 1)[1]),
            ],
            limit=1,
        )
    )
    if data and data.model == "ir.model":
        return env_()["ir.model"].sudo().browse(data.res_id).model
    name = ref.split(".", 1)[1].removeprefix("model_")
    registry = env_().registry
    return next((m for m in registry.models if m.replace(".", "_") == name), None)


def resolved(model: str, anchor: Anchor) -> Anchor:
    registry = env_().registry
    return infer_company_variant(registry[model], anchor, registry.models)


def wanted(part: Part) -> Anchor:
    kind = KIND_OF_RUNG[(part.reach, part.kind)]
    return Anchor(
        part.path,
        kind,
        part.unset,
        part.hierarchy if kind == "company" else "",
        part.usage or None,
    )


def same(a: Anchor, b: Anchor) -> bool:
    return (a.path, a.kind, bool(a.shared), a.hierarchy or "", a.usage or None) == (
        b.path,
        b.kind,
        bool(b.shared),
        b.hierarchy or "",
        b.usage or None,
    )


def key_name(kind: str, anchor: Anchor, taken: set[str]) -> str:
    # a second anchor of a kind, named after its path
    stem = "_".join(
        part.removesuffix("_ids").removesuffix("_id") for part in anchor.path.split(".")
    )
    if anchor.usage:
        stem = f"{anchor.usage}_{stem}"
    if anchor.shared:
        stem = f"{stem}_or_unset"
    name, index = stem, 2
    while name in taken or (name in ANCHOR_KINDS and name != kind):
        name = f"{stem}_{index}"
        index += 1
    return name


def declaration(anchor: Anchor, key: str, model: str) -> str:
    # the smallest spelling that states the anchor: a bare path when the key
    # is its kind and the registry infers the rest
    registry = env_().registry
    bare = Anchor(anchor.path, key if key in ANCHOR_KINDS else anchor.kind)
    if key in ANCHOR_KINDS and same(resolved(model, bare), anchor):
        return repr(anchor.path)
    args = [repr(anchor.path)]
    if key not in ANCHOR_KINDS or key != anchor.kind:
        args.append(f"kind={anchor.kind!r}")
    probe = resolved(model, Anchor(anchor.path, anchor.kind))
    if anchor.kind == "company":
        if bool(probe.shared) != bool(anchor.shared):
            args.append(f"shared={bool(anchor.shared)!r}")
        if (probe.hierarchy or "") != (anchor.hierarchy or ""):
            args.append(f"hierarchy={anchor.hierarchy or ''!r}")
    elif anchor.shared:
        args.append("shared=True")
    if anchor.usage:
        args.append(f"usage={anchor.usage!r}")
    del registry
    return f"models.Anchor({', '.join(args)})"


def static_reads_search(model, static: str) -> bool:
    # a fixed filter naming a field that is not stored and has a search reads
    # something the recognizer cannot see: the user, perhaps
    if not static:
        return False
    registry = env_().registry
    for leaf in ast.literal_eval(static):
        if not isinstance(leaf, (list, tuple)) or len(leaf) != 3:
            continue
        current = model
        for name in str(leaf[0]).split("."):
            field = current._fields.get(name)
            if field is None:
                break
            if not field.store and field.search:
                return True
            if not field.comodel_name or field.comodel_name not in registry:
                break
            current = registry[field.comodel_name]
    return False


def plan():
    registry = env_().registry
    rows = []
    unknown_models = Counter()
    for module, path, xmlid, values, ids in module_rows():
        # a row with a domain and no reach, or the reach all whose filter
        # names a field that reads the user (S2 took it for a fixed filter)
        if not values["domain"] or values["reach"] not in (None, "", "all"):
            continue
        model = model_name(module.name, values["model"])
        proposal = propose(values["domain"], values["kind"] or "")
        if (
            proposal
            and values["reach"] == "all"
            and all(p.reach == "all" for p in proposal.parts)
        ):
            continue
        proven = bool(proposal) and proves(values["domain"], proposal)
        if (
            proven
            and model in registry
            and any(
                static_reads_search(registry[model], p.static) for p in proposal.parts
            )
        ):
            proven = False
        if proven and any(
            f"{xmlid}_{index}" in ids for index in range(2, len(proposal.parts) + 1)
        ):
            proven = False
        rows.append(
            {
                "module": module.name,
                "file": str(path),
                "xmlid": xmlid,
                "model": model,
                "kind": values["kind"],
                "domain": values["domain"],
                "parts": [
                    p.__dict__ if hasattr(p, "__dict__") else _part(p)
                    for p in proposal.parts
                ]
                if proven
                else None,
            }
        )
        if proven and (model is None or model not in registry):
            unknown_models[model or values["model"]] += 1
    # the anchors each model's rows need, keys assigned once per model
    needs: dict[str, list[Anchor]] = defaultdict(list)
    for row in rows:
        if not row["parts"] or row["model"] not in registry:
            continue
        for p in row["parts"]:
            part = Part(**{**p, "args": tuple(map(tuple, p.get("args", ())))})
            if part.reach in ("all", "none", "predicate"):
                continue
            needs[row["model"]].append(wanted(part))
    keys: dict[str, dict[tuple, str]] = {}
    declarations: dict[str, dict[str, str]] = defaultdict(dict)
    for model, anchors in needs.items():
        existing = registry.model_anchors.get(model, {})
        by_kind = Counter((a.kind, a.path) for a in anchors)
        taken = set(existing)
        chosen: dict[tuple, str] = {}
        chosen_anchor: dict[str, tuple] = {}
        for anchor in sorted(
            {
                (a.path, a.kind, bool(a.shared), a.hierarchy or "", a.usage)
                for a in anchors
            },
            key=lambda t: (-by_kind[(t[1], t[0])], t),
        ):
            anchor = Anchor(*anchor)
            match = next((k for k, e in existing.items() if same(e, anchor)), None)
            if match is None and anchor.kind == "company":
                # a model has one company anchor: declare it where the
                # registry infers another, so scoped grants read it too
                declarations[model]["company"] = declaration(anchor, "company", model)
                taken.add("company")
                match = "company"
            elif match is None:
                default = anchor.kind
                twin = existing.get(default) or (
                    Anchor(*chosen_anchor[default])
                    if default in chosen_anchor
                    else None
                )
                if default not in taken:
                    key = default
                elif twin is not None and twin.path == anchor.path and anchor.shared:
                    key = f"{default}_or_unset"
                else:
                    key = key_name(anchor.kind, anchor, taken)
                taken.add(key)
                declarations[model][key] = declaration(anchor, key, model)
                match = key
            chosen_anchor[match] = (
                anchor.path,
                anchor.kind,
                anchor.shared,
                anchor.hierarchy,
                anchor.usage,
            )
            chosen[
                (
                    anchor.path,
                    anchor.kind,
                    bool(anchor.shared),
                    anchor.hierarchy or "",
                    anchor.usage,
                )
            ] = match
        keys[model] = chosen
    for row in rows:
        if not row["parts"] or (
            row["model"] not in keys
            and any(
                p["reach"] not in ("all", "none", "predicate") for p in row["parts"]
            )
        ):
            continue
        for p in row["parts"]:
            if p["reach"] in ("all", "none", "predicate"):
                p["anchor"] = ""
                continue
            anchor = wanted(
                Part(
                    **{
                        **{k: v for k, v in p.items() if k != "anchor"},
                        "args": tuple(map(tuple, p.get("args", ()))),
                    }
                )
            )
            key = keys[row["model"]][
                (
                    anchor.path,
                    anchor.kind,
                    bool(anchor.shared),
                    anchor.hierarchy or "",
                    anchor.usage,
                )
            ]
            p["anchor"] = "" if key == REACH_ANCHOR.get(p["reach"]) else key
    return rows, declarations, unknown_models


def _part(p):
    return {f: getattr(p, f) for f in Part.__dataclass_fields__}


rows, declarations, unknown = plan()
converted = [r for r in rows if r["parts"]]
summary = {
    "rows_with_domain": len(rows),
    "converted": len(converted),
    "rows_after": sum(len(r["parts"]) for r in converted),
    "split": sum(1 for r in converted if len(r["parts"]) > 1),
    "floor": len(rows) - len(converted),
    "models_declaring": len(declarations),
    "declarations": sum(len(v) for v in declarations.values()),
    "declarations_by_kind": dict(
        Counter(
            (d.split("kind=")[1].split(",")[0].strip("')\"") if "kind=" in d else k)
            for m in declarations.values()
            for k, d in m.items()
        )
    ),
    "rows_on_models_not_in_this_registry": sum(unknown.values()),
}
OUT.write_text(
    json.dumps(
        {
            "summary": summary,
            "rows": rows,
            "declarations": declarations,
            "unknown": unknown,
        },
        indent=1,
        default=str,
    ),
    encoding="utf-8",
)
print("REACH_PLAN", json.dumps(summary))
