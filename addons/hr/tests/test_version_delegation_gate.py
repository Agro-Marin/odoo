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
        """Fields whose explicit declarations add up to exactly the inherited field.

        Judged on the MERGED field, not on each declaration: two declarations
        that cancel each other (readonly=False, then readonly=True) leave the
        field equal to the parent and are both dead weight, while one of them
        alone would look like a difference.
        """
        Employee = self.env["hr.employee"]
        Version = self.env["hr.version"]
        Partner = self.env["res.partner"]
        found = []
        for name, field in Employee._fields.items():
            related = field.related or ""
            if not related.startswith("version_id.") or related.count(".") != 1:
                continue
            if name in Partner._fields:
                # Both parents declare it; the declaration says which one wins.
                continue
            parent = Version._fields.get(related.split(".")[1])
            if parent is None or parent.name != name:
                continue
            declared = [
                base
                for base in getattr(field, "_base_fields__", ())
                if "inherited_field" not in base._args__
            ]
            if not declared:
                continue
            if any(set(base._args__) - RESTATABLE for base in declared):
                continue
            same = (
                field.type == parent.type
                and field.readonly == parent.readonly
                and (field.groups or None) == (parent.groups or None)
                and field.string == parent.string
                and (field.help or None) == (parent.help or None)
            )
            if same:
                found.extend((name, base._module) for base in declared)
        return sorted(found)

    def test_no_employee_field_merely_restates_its_version_field(self):
        self.assertFalse(
            self._restatements(),
            "these hr.employee declarations repeat what _inherits hr.version "
            "already provides; delete them, or give them the attribute that "
            "justifies them",
        )

    def test_a_name_on_both_employee_and_version_is_stored_once(self):
        """A name both models declare (by different modules) may be a pointer
        from one side to the other; it may not be two stored columns, which is
        two truths nothing keeps equal. hr's own shared names (active,
        company_id, name) are declared by hr on both sides and mean different
        things there; they are not in scope here."""
        Employee = self.env["hr.employee"]._fields
        Version = self.env["hr.version"]._fields
        magic = {
            "id",
            "display_name",
            "create_uid",
            "create_date",
            "write_uid",
            "write_date",
        }
        twice = []
        for name in set(Employee) & set(Version):
            if name in magic or Employee[name].inherited:
                continue
            if set(Employee[name]._modules or ()) & set(Version[name]._modules or ()):
                continue
            if Employee[name].store and Version[name].store:
                twice.append(name)
        self.assertFalse(
            sorted(twice),
            "hr.employee and hr.version both store these; one side must be a "
            "related to the other",
        )
