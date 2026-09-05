from __future__ import annotations

import json

from odoo.addons.document_extract.tools.schema import Schema

_EXAMPLES = {
    "str": "text, or null",
    "int": "whole number, or null",
    "float": "number, or null",
    "bool": "true or false",
    "date": "YYYY-MM-DD, or null",
    "list": ["..."],
    "dict": {"...": "..."},
}


def _row(spec) -> list:
    return [{name: _EXAMPLES[item.type] for name, item in spec.items.items()}]


def _shape(schema: Schema, names: tuple[str, ...]) -> dict:
    shape = {}
    for name in names:
        spec = schema.fields.get(name)
        if spec is None:
            continue
        shape[name] = _row(spec) if spec.items else _EXAMPLES[spec.type]
    return shape


def _describe(schema: Schema, names: tuple[str, ...]) -> list[str]:
    lines = []
    for name in names:
        spec = schema.fields.get(name)
        if spec is None:
            continue
        note = spec.help or ""
        if spec.required:
            note = f"{note} (required)".strip()
        if spec.items:
            required = [n for n, item in spec.items.items() if item.required]
            if required:
                note = (
                    f"{note} -- a row without {' and '.join(required)} is not a row"
                ).strip()
        if note:
            lines.append(f"- {name}: {note}")
    return lines


def prepare_prompt(schema: Schema, wanted: tuple[str, ...] = ()) -> str:
    names = tuple(wanted) or tuple(schema.fields)
    names = tuple(name for name in names if name in schema.fields)
    if not names:
        names = tuple(schema.fields)

    described = _describe(schema, names)
    rules = [
        f"- {rule.message}"
        for rule in schema.rules
        if rule.message and set(rule.fields) & set(names)
    ]

    parts = [
        f"Read this {schema.name.replace('_', ' ')} and return ONLY valid JSON.",
        "",
        "Expected JSON structure:",
        json.dumps(_shape(schema, names), indent=2),
        "",
        "Rules:",
        "- Return only the JSON object, with no explanation and no markdown",
        "- Use null for anything the document does not state",
        "- Never invent a value, and never carry one over from another document",
        "- Copy numbers exactly as printed, without rounding or reformatting",
        "- Dates as YYYY-MM-DD",
    ]
    if described:
        parts += ["", "Fields:", *described]
    if rules:
        parts += [
            "",
            "These must hold, and are how the answer is checked:",
            *rules,
        ]
    return "\n".join(parts)
