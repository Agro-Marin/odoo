import re
from pathlib import Path

from lxml import etree

from odoo.tests import TransactionCase, tagged

#: An access-group spec is a comma-separated list of xmlids, optionally negated
#: (``account.group_account_user,!base.group_portal``). An OWL prop called
#: ``groups`` holds a JS expression instead, and those are legitimate.
_GROUP_SPEC = re.compile(
    r"^!?[a-z0-9_]+\.[a-z0-9_]+(\s*,\s*!?[a-z0-9_]+\.[a-z0-9_]+)*$"
)

_STATIC = Path(__file__).resolve().parents[1] / "static"


@tagged("post_install", "-at_install")
class TestStaticTemplates(TransactionCase):
    """``groups`` is a server-side QWeb directive. Client-side templates are
    parsed by ``XMLAsset`` and compiled by OWL, neither of which knows the
    attribute, so one written here restricts nobody -- it only tells the next
    reader that access is controlled when it is not.
    """

    def test_no_access_group_attribute_in_static_templates(self):
        offenders = []
        scanned = 0
        for path in sorted(_STATIC.rglob("*.xml")):
            try:
                root = etree.parse(str(path)).getroot()
            except etree.XMLSyntaxError:
                continue
            scanned += 1
            for element in root.iter():
                if callable(element.tag):
                    continue
                for attribute in ("groups", "t-groups"):
                    value = element.get(attribute)
                    if value and _GROUP_SPEC.match(value.strip()):
                        offenders.append(
                            f"{path.relative_to(_STATIC.parent)}:"
                            f"{element.sourceline} -> {attribute}={value!r}"
                        )

        self.assertGreater(scanned, 20, "the scan reached almost no template")
        self.assertFalse(
            offenders,
            "access groups are not applied to client-side templates; these "
            "attributes are inert and only feign a restriction:\n  "
            + "\n  ".join(offenders),
        )
