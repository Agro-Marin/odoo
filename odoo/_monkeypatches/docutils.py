from typing import Any

import docutils.nodes
import docutils.parsers.rst.directives.admonitions
import docutils.parsers.rst.states


def _role_literal(
    name: str,
    rawtext: str,
    text: str,
    lineno: int,
    inliner: docutils.parsers.rst.states.Inliner,
    options: dict[str, Any] | None = None,
    content: list[str] | None = None,
) -> tuple[list[docutils.nodes.Node], list[docutils.nodes.system_message]]:
    literal = docutils.nodes.literal(rawtext, text)
    return [literal], []


def patch_module() -> None:
    for role in (
        "attr",
        "class",
        "func",
        "meth",
        "ref",
        "const",
        "samp",
        "term",
    ):
        docutils.parsers.rst.roles.register_local_role(role, _role_literal)

    for directive in ("attribute", "deprecated"):
        docutils.parsers.rst.directives.register_directive(
            directive, docutils.parsers.rst.directives.admonitions.Note
        )
