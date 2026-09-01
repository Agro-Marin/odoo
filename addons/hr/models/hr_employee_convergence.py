from odoo import api, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    @api.model
    def report_party_convergence(self):
        """What converging work_contact_id with the user's partner would do.

        ADR-0086 step 5. An employee can hold two partner rows for one person --
        the work contact, and the partner behind their login user -- and the
        dissolution needs them to be one. That is a deduplication, not a column
        copy, so this reports what a migration WOULD do and writes nothing.

        Read it before running any convergence. The counts are the safe part;
        `conflicting` is the list a human has to decide about, because the two
        rows may hold different values for the same field and no rule can say
        which is right.
        """
        report = {
            "total": 0,
            "already_converged": 0,
            "no_user": 0,
            "no_work_contact": 0,
            "divergent": 0,
            "conflicting": [],
            "safe_to_merge": [],
        }
        fields_to_compare = ("email", "phone", "mobile", "street", "city", "zip")

        for employee in self.sudo().with_context(active_test=False).search([]):
            report["total"] += 1
            contact = employee.work_contact_id
            user_partner = employee.user_id.partner_id
            if not contact:
                report["no_work_contact"] += 1
                continue
            if not user_partner:
                report["no_user"] += 1
                continue
            if contact == user_partner:
                report["already_converged"] += 1
                continue

            report["divergent"] += 1
            clashes = {
                name: (contact[name], user_partner[name])
                for name in fields_to_compare
                if contact[name]
                and user_partner[name]
                and contact[name] != user_partner[name]
            }
            entry = {
                "employee": employee.display_name,
                "employee_id": employee.id,
                "work_contact": (contact.id, contact.display_name),
                "user_partner": (user_partner.id, user_partner.display_name),
                "clashes": clashes,
            }
            if clashes:
                report["conflicting"].append(entry)
            else:
                report["safe_to_merge"].append(entry)
        return report

    @api.model
    def print_party_convergence(self):
        """The same report, as text, for reading in odoo-bin shell."""
        r = self.report_party_convergence()
        lines = [
            "employees                : %s" % r["total"],
            "  already one partner    : %s" % r["already_converged"],
            "  no login user          : %s" % r["no_user"],
            "  no work contact        : %s" % r["no_work_contact"],
            "  two partners, divergent: %s" % r["divergent"],
            "      of those, mergeable: %s" % len(r["safe_to_merge"]),
            "      needing a decision : %s" % len(r["conflicting"]),
        ]
        for entry in r["conflicting"]:
            lines.append("")
            lines.append(
                "  %s (employee %s)" % (entry["employee"], entry["employee_id"])
            )
            lines.append("    work contact %s: %s" % entry["work_contact"])
            lines.append("    user partner %s: %s" % entry["user_partner"])
            for name, (left, right) in entry["clashes"].items():
                lines.append("      %-8s %r vs %r" % (name, left, right))
        return "\n".join(lines)

    @api.model
    def converge_party_rows(self, limit=None):
        """Merge the two partner rows where they do not disagree. Refuses the rest.

        ADR-0086 step 5, the write half of report_party_convergence(). It acts
        ONLY on employees the report calls safe_to_merge -- the two rows hold no
        conflicting value -- and leaves every conflicting one untouched. Where
        the rows disagree, no rule can say which is right, so a human decides
        and this does not.

        The merge itself goes through base.partner.merge.automatic.wizard._merge
        rather than repointing work_contact_id by hand: that is what already
        knows to move every foreign key, reparent children, fold bank accounts
        and refuse a merge between a contact and its own ancestor. Reproducing
        any of that here would be a second implementation to keep in step.

        The user's partner is the destination. It is the row that survives
        elsewhere -- it is what res.users points at, what mail addresses, and
        what the identifier record rule tests against user.partner_id.
        """
        report = self.report_party_convergence()
        entries = report["safe_to_merge"][: limit or None]
        Merge = self.env["base.partner.merge.automatic.wizard"].sudo()

        merged = []
        for entry in entries:
            employee = self.browse(entry["employee_id"])
            work_contact = employee.sudo().work_contact_id
            user_partner = employee.sudo().user_id.partner_id
            if not work_contact or not user_partner or work_contact == user_partner:
                continue
            Merge._merge([work_contact.id, user_partner.id], dst_partner=user_partner)
            merged.append(entry["employee_id"])

        return {
            "merged": merged,
            "left_for_a_human": [e["employee_id"] for e in report["conflicting"]],
        }
