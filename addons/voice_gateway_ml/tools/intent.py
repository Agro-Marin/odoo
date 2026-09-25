from __future__ import annotations

from typing import Any

from odoo.exceptions import UserError

from odoo.addons.gateway_ml.tools.router import MlRequest, get_router

INTENT_PURPOSE = "voice.intent"
MAX_CHOICES = 400
MAX_ACTIONS = 6
MAX_SENTENCE_CHARS = 500

SYSTEM = """\
You turn one sentence an Odoo user said into actions on the screen in front of
them. Each line of CHOICES is an id, a tab, and what it does. Answer only with
ids from CHOICES, in the order they should happen. For a choice that says "the
value", put the value in the user's own words in "value"; otherwise leave it
empty. When the sentence asks for nothing on the list, or you are unsure, or
the sentence says not to do something, answer with no action. Never pick a
choice that presses a button or runs a command unless the user asked for
exactly that."""


def intent_schema(ids: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "actions": {
                "type": "array",
                "maxItems": MAX_ACTIONS,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "enum": ids},
                        "value": {"type": "string"},
                    },
                    "required": ["id", "value"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["actions"],
        "additionalProperties": False,
    }


def _clean_choices(choices: Any) -> dict[str, str]:
    if not isinstance(choices, list):
        return {}
    cleaned = {}
    for choice in choices[:MAX_CHOICES]:
        if isinstance(choice, dict) and isinstance(choice.get("id"), str):
            label = str(choice.get("label") or "").replace("\n", " ").replace("\t", " ")
            cleaned[choice["id"]] = label[:200]
    return cleaned


def can_interpret(env: Any) -> bool:
    return bool(
        get_router(env).select_model(
            "chat", company_id=env.company.id, purpose=INTENT_PURPOSE
        )
    )


def interpret_sentence(env: Any, text: str, choices: Any) -> list[dict[str, str]]:
    offered = _clean_choices(choices)
    text = (text or "").strip()[:MAX_SENTENCE_CHARS]
    if not text or not offered:
        return []
    listing = "\n".join(f"{choice_id}\t{label}" for choice_id, label in offered.items())
    result = get_router(env).run(
        "chat",
        MlRequest(
            purpose=INTENT_PURPOSE,
            system=SYSTEM,
            prompt=f"CHOICES:\n{listing}\n\nSENTENCE: {text}",
            response_schema=intent_schema(list(offered)),
            temperature=0,
        ),
        company_id=env.company.id,
    )
    data = result.data if isinstance(result.data, dict) else {}
    actions = data.get("actions")
    if not isinstance(actions, list):
        raise UserError(env._("The model gave no usable answer."))
    return [
        {"id": action["id"], "value": str(action.get("value") or "")}
        for action in actions[:MAX_ACTIONS]
        if isinstance(action, dict) and action.get("id") in offered
    ]
