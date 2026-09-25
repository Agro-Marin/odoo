from odoo import models
from odoo.tools import SQL


class IrAccess(models.Model):
    _inherit = "ir.access"

    def _access_bind_teams(self, usage: str | None) -> list[int]:
        # the teams the principal is an active member of, as res.users'
        # team_ids and <usage>_team_ids read them, in SQL: the rows are
        # compiled for any principal, portal and public included
        self.env["team.member"].flush_model(["user_id", "team_id", "active"])
        condition = SQL()
        if usage:
            flag = self.env["team.team"]._get_usage(usage).flag
            self.env["team.team"].flush_model([flag])
            condition = SQL("AND team.%s", SQL.identifier(flag))
        self.env.cr.execute(
            SQL(
                """
                SELECT DISTINCT member.team_id
                  FROM team_member member
                  JOIN team_team team ON team.id = member.team_id
                 WHERE member.user_id = %s AND member.active %s
                 ORDER BY 1
                """,
                self.env.uid,
                condition,
            )
        )
        return [team_id for (team_id,) in self.env.cr.fetchall()]
