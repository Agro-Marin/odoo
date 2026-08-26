from __future__ import annotations

import logging

from odoo import models
from odoo.fields import Domain

_logger = logging.getLogger(__name__)


class HrApplicant(models.Model):
    _inherit = "hr.applicant"

    def _update_from_extraction(self, result) -> None:
        self.ensure_one()
        super()._update_from_extraction(result)

        names = self._get_extract_skill_names(result.flat().get("skills"))
        if names:
            self._add_extracted_skills(names)

    def _get_extract_skill_names(self, skills) -> list[str]:
        if not skills:
            return []
        names = []
        for skill in skills:
            name = skill.get("name") if isinstance(skill, dict) else skill
            if isinstance(name, str) and name.strip():
                names.append(name.strip())
        return names

    def _add_extracted_skills(self, names: list[str]) -> None:
        self.ensure_one()
        # `in` is case-sensitive in SQL, so it would filter the catalogue down
        # before the case-insensitive match below ever runs.
        catalogue = self.env["hr.skill"].search(
            Domain.OR([Domain("name", "=ilike", name) for name in names])
        )
        by_name = {skill.name.casefold(): skill for skill in catalogue}

        wanted = self.env["hr.skill"]
        for name in names:
            skill = by_name.get(name.casefold())
            if skill:
                wanted |= skill
            else:
                _logger.info(
                    "CV names the skill %r, which the catalogue does not carry", name
                )

        missing = wanted - self.applicant_skill_ids.skill_id
        vals = []
        for skill in missing:
            levels = skill.skill_type_id.skill_level_ids
            level = levels.filtered("default_level")[:1] or levels[:1]
            if not level:
                _logger.info(
                    "Skill %r has no level to assign; not attached", skill.name
                )
                continue
            vals.append(
                {
                    "applicant_id": self.id,
                    "skill_id": skill.id,
                    "skill_type_id": skill.skill_type_id.id,
                    "skill_level_id": level.id,
                }
            )
        if vals:
            self.env["hr.applicant.skill"].create(vals)
