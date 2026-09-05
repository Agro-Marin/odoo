from odoo.tests import TransactionCase, tagged

RESTATABLE = frozenset({"related", "inherited", "readonly", "groups", "string", "help"})


@tagged("post_install", "-at_install")
class TestVersionDelegationGate(TransactionCase):
    """A field hr.employee declares as ``related="version_id.x"`` must add something.

    ``_inherits`` already hands the employee every version field with the
    version's readonly, groups and inverse; a declaration that repeats those is a
    second copy of the parent's policy that drifts on its own. It is legitimate
    only when it changes an attribute the inherited field would not carry.
    """

    def _restatements(self):
        Employee = self.env["hr.employee"]
        Version = self.env["hr.version"]
        found = []
        for name, field in Employee._fields.items():
            related = field.related or ""
            if not related.startswith("version_id.") or related.count(".") != 1:
                continue
            parent = Version._fields.get(related.split(".")[1])
            if parent is None or parent.name != name:
                continue
            for base in field._args__.get("_base_fields__", (field,)):
                args = dict(base._args__)
                if "inherited_field" in args or base.type != parent.type:
                    continue
                if args.get("string") in (None, parent.string):
                    args.pop("string", None)
                if set(args) - RESTATABLE:
                    continue
                if args.get("readonly", parent.readonly) != parent.readonly:
                    continue
                if (args.get("groups", parent.groups) or None) != (
                    parent.groups or None
                ):
                    continue
                if (args.get("help", parent.help) or None) != (parent.help or None):
                    continue
                found.append((name, base._module))
        return sorted(found)

    def test_no_employee_field_merely_restates_its_version_field(self):
        self.assertFalse(
            self._restatements(),
            "these hr.employee declarations repeat what _inherits hr.version "
            "already provides; delete them, or give them the attribute that "
            "justifies them",
        )
