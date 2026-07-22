# Part of Odoo. See LICENSE file for full copyright and licensing details.
from collections import defaultdict

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain


class HrIndividualSkillMixin(models.AbstractModel):
    _name = 'hr.individual.skill.mixin'
    _description = "Skill level"
    _order = "skill_type_id, skill_level_id"
    _rec_name = "skill_id"

    def _linked_field_name(self):
        raise NotImplementedError

    def _get_passive_fields(self):
        """Return extra field names to copy onto new (versioned) skills.

        :return: list of field names to copy to new skills
        :rtype: list[str]
        """
        # Passive fields are carried over when a new skill version is created
        # because a core/active field changed (linked_field, skill_id,
        # skill_level_id, skill_type_id), but editing a passive field does NOT
        # itself trigger a new version. Core/active fields are preserved
        # automatically and must NOT be listed here.
        return []

    def _can_edit_certification_validity_period(self):
        # If True, the overlapping constraint on a certification is released:
        # two certifications are overlapping each other if they have the same skill_level_id, valid_from and valid_to.
        # This behavior is wanted when the user can change the validity.
        return True

    def _default_skill_type_id(self):
        if self.env.context.get('certificate_skill', False):
            return self.env['hr.skill.type'].search([('is_certification', '=', True)], limit=1)
        return self.env['hr.skill.type'].search([], limit=1)

    skill_id = fields.Many2one('hr.skill', compute='_compute_skill_id', store=True,
        domain="[('skill_type_id', '=', skill_type_id)]", readonly=False, required=True, ondelete='cascade')
    skill_level_id = fields.Many2one('hr.skill.level', compute='_compute_skill_level_id',
        domain="[('skill_type_id', '=', skill_type_id)]", store=True, readonly=False, required=True, ondelete='cascade')
    skill_type_id = fields.Many2one('hr.skill.type',
                                    default=_default_skill_type_id,
                                    required=True, ondelete='cascade')
    level_progress = fields.Integer(related='skill_level_id.level_progress')
    color = fields.Integer(related="skill_type_id.color")
    valid_from = fields.Date(string="Validity Start", default=fields.Date.today())
    valid_to = fields.Date(string="Validity Stop")
    levels_count = fields.Integer(related="skill_type_id.levels_count")
    certification_skill_type_count = fields.Integer(compute="_compute_certification_skill_type_count",
        export_string_translation=False)
    is_certification = fields.Boolean(related="skill_type_id.is_certification",
        export_string_translation=False)  # if is_certification change the model will not trigger the constrains
    display_warning_message = fields.Boolean()

    @api.constrains(lambda self: [
        'valid_from', 'valid_to', 'skill_id', 'skill_type_id', 'skill_level_id', self._linked_field_name()
    ])
    def _check_not_overlapping_regular_skill(self):
        """Forbid overlapping regular skills and duplicate certifications for the same record."""
        # Core behaviour and difference between the two models:
        # Skills:
        #   1. Only one active skill per skill_id (e.g. only one level of English).
        #   2. Skills are not deleted unless created within the last 24 hours;
        #      otherwise they are archived to preserve the record's skill history.
        #   3. Skills are not written to in place: the previous skill is archived
        #      and a new one with the new values is created, again to keep history.
        # Certifications:
        #   1. Many certifications with the same skill_id and skill_level may exist
        #      as long as valid_from/valid_to differ, e.g. "Odoo:Certified
        #      2025-1-1 to 2025-12-31" alongside "Odoo:Certified 2024-6-1 to 2025-5-31".
        #   2. Certifications can be deleted at any point.
        #   3. Certifications are not written to in place: the previous one is
        #      archived and a new one with the new values is created.
        # For both models:
        #   1. No two records may have exactly the same values.
        #   2. A record is active when valid_to is unset or set to a future date.
        overlapping_dict = self._get_overlapping_individual_skill([{
                f"{self._linked_field_name()}": skill_ind[self._linked_field_name()].id,
                "skill_id": skill_ind.skill_id.id,
                "id": skill_ind.id,
                "valid_from": skill_ind.valid_from,
                "valid_to": skill_ind.valid_to,
                "skill_level_id": skill_ind.skill_level_id.id,
                "is_certification": skill_ind.is_certification
            }
        for skill_ind in self])
        if overlapping_dict:
            errors = []
            for existing_ind_skill, new_ind_skills in overlapping_dict.items():
                errors.append(
                    f"• {', '.join([str(ind_skill) for ind_skill in new_ind_skills])} conflicts with the existing skill/certification {existing_ind_skill.display_name} from {existing_ind_skill.valid_from} to {existing_ind_skill.valid_to}",
                )

            error_msg = self.env._(
                "The following skills can't be created as they overlap or exactly match existing skills:\n%(collisions)s",
                collisions="\n".join(errors),
            )
            raise ValidationError(error_msg)

    def _get_overlapping_individual_skill(self, vals_list):
        can_edit_certification_validity_period = self._can_edit_certification_validity_period()
        matching_skill_domain = Domain.FALSE
        overlapping_dict = defaultdict(list)
        certification_dict = defaultdict(list)
        regular_dict = defaultdict(list)
        for individual_skill_vals in vals_list:
            ind_domain = Domain.AND([
                Domain(f"{self._linked_field_name()}.id", "=", individual_skill_vals[self._linked_field_name()]),
                Domain("skill_id.id", "=", individual_skill_vals['skill_id']),
                Domain("id", "!=", individual_skill_vals['id']),
            ])

            if can_edit_certification_validity_period and individual_skill_vals['is_certification']:
                ind_domain = Domain.AND([
                    ind_domain,
                    Domain("skill_level_id.id", "=", individual_skill_vals['skill_level_id']),
                    Domain('valid_from', '=', individual_skill_vals['valid_from']),
                    Domain('valid_to', '=', individual_skill_vals['valid_to']),
                ])
                key = (
                    individual_skill_vals[self._linked_field_name()],
                    individual_skill_vals['skill_id'],
                    individual_skill_vals['skill_level_id'],
                    fields.Date.from_string(individual_skill_vals['valid_from']),
                    fields.Date.from_string(individual_skill_vals['valid_to']),
                )
                certification_dict[key].append(individual_skill_vals)
            else:
                ind_domain = Domain.AND([
                    ind_domain,
                    Domain.OR([
                        Domain.AND([
                            Domain('valid_from', '<=', individual_skill_vals['valid_from']),
                            Domain.OR([
                                Domain('valid_to', '=', False),
                                Domain('valid_to', '>=', individual_skill_vals['valid_from']),
                            ]),
                        ]),
                        Domain.AND([
                            Domain('valid_from', '<=', individual_skill_vals['valid_to']),
                            Domain.OR([
                                Domain('valid_to', '=', False),
                                Domain('valid_to', '>=', individual_skill_vals['valid_to']),
                            ]),
                        ]),
                    ])
                ])

                key = (
                    individual_skill_vals[self._linked_field_name()],
                    individual_skill_vals['skill_id'],
                )
                regular_dict[key].append(individual_skill_vals)

            matching_skill_domain = Domain.OR([matching_skill_domain, ind_domain])
        matching_individual_skills = self.env[self._name].search(matching_skill_domain)
        for matching_ind_skill in matching_individual_skills:
            if can_edit_certification_validity_period and matching_ind_skill.is_certification:
                similar_certifications = certification_dict.get((
                    matching_ind_skill[self._linked_field_name()].id,
                    matching_ind_skill.skill_id.id,
                    matching_ind_skill.skill_level_id.id,
                    fields.Date.from_string(matching_ind_skill.valid_from),
                    fields.Date.from_string(matching_ind_skill.valid_to),
                ))
                if similar_certifications:
                    overlapping_dict[matching_ind_skill].extend(similar_certifications)
            else:
                similar_regular_skills = regular_dict.get((
                    matching_ind_skill[self._linked_field_name()].id,
                    matching_ind_skill.skill_id.id,
                ), [])
                for similar_regular_skill in similar_regular_skills:
                    if (matching_ind_skill.valid_from <= similar_regular_skill['valid_from'] and
                        (not matching_ind_skill.valid_to or
                        matching_ind_skill.valid_to >= similar_regular_skill['valid_from']
                    )) or (matching_ind_skill.valid_from <= similar_regular_skill['valid_to'] and
                        (not matching_ind_skill.valid_to or
                        matching_ind_skill.valid_to >= similar_regular_skill['valid_to']
                    )):
                        overlapping_dict[matching_ind_skill].append(similar_regular_skill)
        return overlapping_dict

    @api.constrains('valid_from', 'valid_to')
    def _check_date(self):
        error_ind_skill_msg = ""
        for ind_skill in self:
            if ind_skill.valid_to and ind_skill.valid_from > ind_skill.valid_to:
                error_ind_skill_msg += self.env._("• %(skill_name)s from %(valid_from)s to %(valid_to)s",
                    skill_name=ind_skill.display_name, valid_from=ind_skill.valid_from, valid_to=ind_skill.valid_to
                )
        if error_ind_skill_msg:
            raise ValidationError(self.env._("The following skills have their valid stop date prior to their valid start date:\n") + error_ind_skill_msg)

    @api.constrains('skill_id', 'skill_type_id')
    def _check_skill_type(self):
        for record in self:
            if record.skill_id not in record.skill_type_id.skill_ids:
                raise ValidationError(self.env._("The skill %(name)s and skill type %(type)s don't match",
                    name=record.skill_id.name, type=record.skill_type_id.name))

    @api.constrains('skill_type_id', 'skill_level_id')
    def _check_skill_level(self):
        for record in self:
            if record.skill_level_id not in record.skill_type_id.skill_level_ids:
                raise ValidationError(self.env._("The skill level %(level)s is not valid for skill type: %(type)s",
                    level=record.skill_level_id.name, type=record.skill_type_id.name))

    def _compute_certification_skill_type_count(self):
        certification_skill_type_count = self.env['hr.skill.type'].search_count(domain=[('is_certification', '=', True)])
        self.certification_skill_type_count = certification_skill_type_count

    #  To reset the validity period if the skill become certified or uncertified
    @api.onchange('is_certification')
    def _onchange_is_certification(self):
        self.valid_from = fields.Date.today()
        if not self.is_certification:
            self.valid_to = False

    @api.depends('skill_type_id')
    def _compute_skill_id(self):
        for record in self:
            if record.skill_type_id:
                record.skill_id = record.skill_type_id.skill_ids[0] if record.skill_type_id.skill_ids else False
            else:
                record.skill_id = False

    @api.depends('skill_id')
    def _compute_skill_level_id(self):
        for record in self:
            if not record.skill_id:
                record.skill_level_id = False
            else:
                skill_levels = record.skill_type_id.skill_level_ids
                record.skill_level_id = skill_levels.filtered('default_level') or skill_levels[0] if skill_levels else False

    @api.depends('skill_id', 'skill_level_id')
    def _compute_display_name(self):
        for individual_skill in self:
            individual_skill.display_name = f"{individual_skill.skill_id.name}: {individual_skill.skill_level_id.name}"

    @api.onchange('valid_to', 'valid_from')
    def _onchange_valid_date(self):
        self.display_warning_message = self.valid_to and self.valid_from and self.valid_to < self.valid_from

    def _expire_individual_skills(self):
        """Archive or delete every individual skill in ``self``.

        :return: list of WRITE and DELETE (x2many) commands
        :rtype: list
        """
        # A skill created within the last 24h (valid_from >= yesterday) or already
        # expired (valid_to <= yesterday) is deleted. Otherwise it is archived by
        # setting valid_to to yesterday, unless doing so would break a constraint
        # (overlap), in which case it is deleted instead.
        yesterday = fields.Date.today() - relativedelta(days=1)
        to_remove = self.env[self._name]
        to_archive = self.env[self._name]
        for individual_skill in self:
            if individual_skill.valid_from >= yesterday or (individual_skill.valid_to and individual_skill.valid_to <= yesterday):
                to_remove += individual_skill
            else:
                to_archive += individual_skill
        if to_archive:
            overlapping_dict = self._get_overlapping_individual_skill([{
                    f"{self._linked_field_name()}": skill[self._linked_field_name()].id,
                    "skill_id": skill.skill_id.id,
                    "id": skill.id,
                    "valid_from": skill.valid_from,
                    "valid_to": yesterday,
                    "skill_level_id": skill.skill_level_id.id,
                    "is_certification": skill.is_certification
            } for skill in to_archive])
            new_overlapped_skill_ids = [
                new_skill['id']
                for new_skills in overlapping_dict.values()
                for new_skill in new_skills
            ]
            changed_to_remove = to_archive.filtered(lambda ind_skill: ind_skill.id in new_overlapped_skill_ids)
            to_archive -= changed_to_remove
            to_remove += changed_to_remove
        return [[2, skill.id] for skill in to_remove] + [[1, skill.id, {'valid_to': yesterday}] for skill in to_archive]

    def _create_individual_skills(self, vals_list):
        """Transform CREATE commands into CREATE, WRITE and DELETE commands.

        :param list vals_list: values dicts from the CREATE commands
        :return: list of CREATE, WRITE and DELETE (x2many) commands
        :rtype: list
        """
        # Archiving the previous skill instead of overwriting it keeps the record
        # logs/history and keeps the overlap constraints satisfied.
        can_edit_certification_validity_period = self._can_edit_certification_validity_period()
        seen_skills = set()
        skills_to_archive = self.env[self._name]
        vals_to_return = []

        validity_domain = Domain.OR(
            [
                Domain("valid_to", "=", False),
                Domain("valid_to", ">=", fields.Date.today()),
            ]
        )

        if can_edit_certification_validity_period:
            validity_domain = Domain.OR([
                validity_domain,
                Domain("is_certification", "=", True),
            ])

        existing_skills_domain = Domain.AND(
            [
                Domain.OR(
                    [
                        Domain.AND(
                            [
                                Domain(f"{self._linked_field_name()}", "=", vals.get(self._linked_field_name(), False)),
                                Domain("skill_id", "=", vals.get("skill_id", False)),
                            ]
                        )
                        for vals in vals_list
                    ]
                ),
                validity_domain
            ]
        )

        existing_skills = self.env[self._name].search(existing_skills_domain)
        existing_skills_grouped = existing_skills.grouped(
            lambda skill: (skill[self._linked_field_name()].id, skill.skill_id.id)
        )

        if can_edit_certification_validity_period:
            existing_certifications = existing_skills.filtered(lambda s: s.is_certification)
            certification_set = {}
            for cert in existing_certifications:
                key = (
                    cert[self._linked_field_name()].id,
                    cert.skill_id.id,
                    cert.skill_level_id.id,
                    fields.Date.from_string(cert.valid_from),
                    fields.Date.from_string(cert.valid_to),
                )
                certification_set[key] = cert

            certification_types = set(
                self.env["hr.skill.type"]
                .browse([vals["skill_type_id"] for vals in vals_list])
                .filtered("is_certification")
                .ids
            )
        for vals in vals_list:
            individual_skill_id = vals.get(self._linked_field_name(), False)
            skill_id = vals["skill_id"]
            skill_type_id = vals["skill_type_id"]
            skill_level_id = vals["skill_level_id"]
            valid_from = fields.Date.from_string(vals.get("valid_from"))
            valid_to = fields.Date.from_string(vals.get("valid_to"))

            if can_edit_certification_validity_period:
                is_certificate = skill_type_id in certification_types
            else:
                is_certificate = False

            skill_key = (individual_skill_id, skill_id, valid_from, valid_to)

            # Remove duplicate skills
            if skill_key in seen_skills:
                continue
            seen_skills.add(skill_key)

            if is_certificate:
                key = (
                    individual_skill_id,
                    skill_id,
                    skill_level_id,
                    valid_from,
                    valid_to,
                )
                # Remove duplicate certification
                if certification_set.get(key):
                    continue
            # Archive existing regular skill if the person already have one with the same skill
            elif existing_skill := existing_skills_grouped.get((individual_skill_id, skill_id)):
                skills_to_archive += existing_skill

            vals_to_return.append(vals)

        return skills_to_archive._expire_individual_skills() + [[0, 0, new_create_val] for new_create_val in vals_to_return]

    def _write_individual_skills(self, commands):
        """Transform WRITE commands into CREATE, WRITE and DELETE commands.

        :param commands: list of WRITE commands
        :return: list of CREATE, WRITE and DELETE (x2many) commands
        :rtype: list
        """
        # If none of skill_type_id, skill_id, skill_level_id or the linked field
        # is being written, this behaves like a standard write. Otherwise the
        # current record is archived (valid_to set to yesterday) and a new one is
        # created from vals merged over self, with vals taking priority.
        self_dict = self.grouped('id')
        result_command = []
        create_vals = []
        remove_from_expire = self.env[self._name]

        def _get_passive_field_value(field, skill):
            """
            Extracts the appropriate value from a field to be passed into a vals dict for record creation/writing.
            Returns the raw value for most fields but extracts id(s) for relational fields.

            :param field: Field name as a string to process
            :param skill: Source record to extract value from
            :return: ORM-ready value for the field
            """
            field_type = self._fields[field].type
            if field_type == "many2one":
                return skill[field].id
            if field_type in ("many2many", "one2many"):
                return skill[field].ids
            return skill[field]

        for command in commands:
            ind_skill = self_dict.get(command[1])
            vals = command[2]
            if not any(key in vals for key in ["skill_type_id", "skill_id", "skill_level_id", self._linked_field_name()]):
                result_command.append([1, ind_skill.id, vals])
                remove_from_expire += ind_skill
                continue

            passive_vals = {
                field: vals.get(field, _get_passive_field_value(field, ind_skill))
                for field in self._get_passive_fields()
            }
            new_vals = {
                f'{self._linked_field_name()}': vals.get(self._linked_field_name(), ind_skill[self._linked_field_name()].id),
                'skill_id': vals.get('skill_id', ind_skill.skill_id.id),
                'skill_level_id': vals.get('skill_level_id', ind_skill.skill_level_id.id),
                'skill_type_id': vals.get('skill_type_id', ind_skill.skill_type_id.id),
                **passive_vals,
            }
            skill_type = self.env['hr.skill.type'].browse(new_vals['skill_type_id'])
            valid_from = vals.get('valid_from', ind_skill.valid_from if skill_type.is_certification else fields.Date.today())
            valid_to = vals.get('valid_to', ind_skill.valid_to if skill_type.is_certification else False)
            new_vals.update({
                'valid_from': valid_from,
                'valid_to': valid_to,
            })
            create_vals.append(new_vals)
        return result_command + (self - remove_from_expire)._expire_individual_skills() + self.env[self._name]._create_individual_skills(create_vals)

    def _get_transformed_commands(self, commands, individuals):
        """Rewrite ORM commands to honour the skill/certification business rules.

        :param commands: list of CREATE, WRITE and UNLINK commands
        :param individuals: recordset of the linked field's model
        :return: list of CREATE, WRITE and UNLINK commands
        """
        # Business rules enforced here:
        # - Skills: only one active skill per skill_id (e.g. one "English" per record).
        # - Certifications (is_certification=True): several with the same skill_id
        #   and skill_level_id may coexist as long as their date ranges differ, e.g.
        #   "Odoo Certified (2024-01-01 → 2024-12-31)" and "(2024-06-01 → 2025-05-31)".
        # - Updates always create a new record and archive the old one instead of
        #   writing in place; no two records may have all fields identical.
        # - A record is active while valid_to is unset or in the future, archived
        #   otherwise, and deleted only when valid_from is within the last 24h or it
        #   is already expired.
        if not commands:
            return None
        updated_ids = set()
        updated_commands = []
        created_values = []
        unlinked_ids = set()
        for command in commands:
            if command[0] == 1:
                updated_ids.add(command[1])
                updated_commands.append(command)
            elif command[0] == 2:
                unlinked_ids.add(command[1])
            elif command[0] == 0:
                if individuals:
                    for individual in individuals:
                        individual_command = command[2]
                        individual_command[self._linked_field_name()] = individual.id
                        created_values.append(individual_command)
                else:
                    created_values.append(command[2])
        mixed_command_ids = list(updated_ids & unlinked_ids)
        if mixed_command_ids:
            # reset updated values
            updated_ids = set()
            updated_commands = []
            for command in commands:
                if command[1] not in mixed_command_ids and command[0] == 1:
                    updated_commands.append(command)
                    updated_ids.append(command[1])
        # Process individual_skill_ids values
        unlinked_commands = self.env[self._name].browse(list(unlinked_ids))._expire_individual_skills()
        updated_commands = self.env[self._name].browse(list(updated_ids))._write_individual_skills(updated_commands)
        created_commands = self.env[self._name]._create_individual_skills(created_values)
        return unlinked_commands + updated_commands + created_commands
