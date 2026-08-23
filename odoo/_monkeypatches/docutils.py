from typing import Any, ClassVar

from docutils import nodes
from docutils.parsers.rst import directives, roles, states
from docutils.parsers.rst.directives.admonitions import Note
from docutils.statemachine import StringList

LITERAL_ROLES = (
    "attr",
    "class",
    "func",
    "meth",
    "ref",
    "const",
    "samp",
    "term",
)


def _role_literal(
    name: str,
    rawtext: str,
    text: str,
    lineno: int,
    inliner: states.Inliner,
    options: dict[str, Any] | None = None,
    content: list[str] | None = None,
) -> tuple[list[nodes.Node], list[nodes.system_message]]:
    return [nodes.literal(rawtext, text)], []


class _AdmonitionWithLead(Note):
    """A Sphinx directive that takes an argument, rendered as a note.

    `Note` accepts no arguments, so `.. deprecated:: 19.0` put the version into
    the *body*: a note whose first paragraph was the bare text "19.0", which
    tells a reader nothing. Sphinx is not a dependency here and will not
    become one; giving the two directives their argument back is the cheap
    half of what it would do.

    The content is optional too -- `.. deprecated:: 19.0` with no body is
    well-formed in Sphinx, and `BaseAdmonition` aborts on it.
    """

    lead: ClassVar[str] = "%s"
    required_arguments = 0
    optional_arguments = 1
    final_argument_whitespace = True

    def run(self) -> list[nodes.Node]:
        if not self.content:
            self.content = StringList(
                [""], source=self.state_machine.document["source"]
            )
        produced = super().run()
        if self.arguments and produced:
            text = self.lead % self.arguments[0]
            produced[0].insert(0, nodes.paragraph("", "", nodes.strong(text, text)))
        return produced


class _Deprecated(_AdmonitionWithLead):
    lead = "Deprecated since version %s"


class _Attribute(_AdmonitionWithLead):
    lead = "Attribute %s"


def patch_module() -> None:
    """Stand in for the Sphinx domain, which is not a dependency.

    Odoo renders reStructuredText in two places -- `ir_module`'s
    `description_html` and `libs/docstring`'s API documentation -- and both
    meet docstrings written for Sphinx. Without these, every `:meth:` renders
    as an "Unknown interpreted text role" error inside the output.
    """
    for role in LITERAL_ROLES:
        roles.register_local_role(role, _role_literal)

    directives.register_directive("deprecated", _Deprecated)
    directives.register_directive("attribute", _Attribute)
