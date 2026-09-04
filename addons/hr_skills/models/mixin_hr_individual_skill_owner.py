from odoo import api, models


class MixinHrIndividualSkillOwner(models.AbstractModel):
    """A record that owns a versioned list of individual skills.

    The client edits a *current* view of the list (and, for employees, a
    certification view of it); every command it sends is translated by the
    skill model's ``_get_transformed_commands`` into the stored one2many, so a
    changed level archives the old row instead of overwriting it.
    """

    _name = "mixin.hr.individual.skill.owner"
    _description = "Owner of individual skills"

    def _individual_skill_field_name(self):
        raise NotImplementedError

    def _individual_skill_command_field_names(self):
        return (self._individual_skill_field_name(),)

    def _individual_skill_model(self):
        return self.env[self._fields[self._individual_skill_field_name()].comodel_name]

    def _pop_individual_skill_commands(self, vals):
        commands = []
        for field_name in self._individual_skill_command_field_names():
            commands += vals.pop(field_name, None) or []
        return commands

    @api.model_create_multi
    def create(self, vals_list):
        stored_field = self._individual_skill_field_name()
        for vals in vals_list:
            if not (set(self._individual_skill_command_field_names()) & vals.keys()):
                continue
            commands = self._pop_individual_skill_commands(vals)
            if commands:
                vals[stored_field] = (
                    self._individual_skill_model()._get_transformed_commands(
                        commands, self.browse()
                    )
                )
        return super().create(vals_list)

    def write(self, vals):
        if not (set(self._individual_skill_command_field_names()) & vals.keys()):
            return super().write(vals)
        commands = self._pop_individual_skill_commands(vals)
        stored_field = self._individual_skill_field_name()
        skill_model = self._individual_skill_model()
        if len(self) > 1:
            result = super().write(vals) if vals else True
            for record in self:
                record.write(
                    {
                        stored_field: skill_model._commands_for_individual(
                            commands, record
                        )
                    }
                )
            return result
        vals[stored_field] = skill_model._get_transformed_commands(commands, self)
        return super().write(vals)
