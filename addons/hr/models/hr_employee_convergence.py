from odoo import api, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    @api.model
    def report_party_convergence(self):
        report = {
            "total": 0,
            "already_converged": 0,
            "no_user": 0,
            "no_work_contact": 0,
            "divergent": 0,
            "misparented_home": [],
            "conflicting": [],
            "safe_to_merge": [],
        }
        fields_to_compare = ("email", "phone", "mobile", "street", "city", "zip")

        for employee in self.sudo().with_context(active_test=False).search([]):
            report["total"] += 1
            contact = employee.partner_id
            home = employee.private_address_id
            if home and contact and home.parent_id != contact:
                report["misparented_home"].append(employee.id)
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
        r = self.report_party_convergence()
        lines = [
            "employees                : %s" % r["total"],
            "  already one partner    : %s" % r["already_converged"],
            "  no login user          : %s" % r["no_user"],
            "  no work contact        : %s" % r["no_work_contact"],
            "  two partners, divergent: %s" % r["divergent"],
            "      of those, mergeable: %s" % len(r["safe_to_merge"]),
            "      needing a decision : %s" % len(r["conflicting"]),
            "  home not under contact : %s" % len(r["misparented_home"]),
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
        report = self.report_party_convergence()
        self.browse(report["misparented_home"])._reparent_private_address()
        entries = report["safe_to_merge"][: limit or None]
        Merge = self.env["base.partner.merge.automatic.wizard"].sudo()

        merged = []
        for entry in entries:
            employee = self.browse(entry["employee_id"])
            work_contact = employee.sudo().partner_id
            user_partner = employee.sudo().user_id.partner_id
            if not work_contact or not user_partner or work_contact == user_partner:
                continue
            Merge._merge([work_contact.id, user_partner.id], dst_partner=user_partner)
            merged.append(entry["employee_id"])

        return {
            "merged": merged,
            "left_for_a_human": [e["employee_id"] for e in report["conflicting"]],
        }
