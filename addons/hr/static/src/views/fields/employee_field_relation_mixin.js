/** @odoo-module native */
import { AvatarCardEmployeePopover } from "@hr/components/avatar_card_employee/avatar_card_employee_popover";
import { onWillStart } from "@odoo/owl";
import { user } from "@web/core/user";
import { usePopover } from "@web/ui/popover";

/**
 * Adds employee-relation behaviour to a relational field component.
 *
 * `@template` rather than `@param { Class }`: a mixin factory whose parameter is
 * typed as a bare `Class` erases the base, so every member the wrapped component
 * declares -- `props`, `components`, `getTagProps` -- is invisible to `tsc` in
 * every subclass of the result. Naming the constructor type and letting the
 * return be INFERRED from the class expression is what preserves both sides: the
 * base's members through `T`, and this mixin's own additions from the body.
 *
 * @template {typeof import("@odoo/owl").Component} T
 * @param {T} fieldClass
 */
export function EmployeeFieldRelationMixin(fieldClass) {
    return class extends fieldClass {
        static props = {
            ...fieldClass.props,
            relation: { type: String, optional: true },
        };

        setup() {
            super.setup();
            onWillStart(async () => {
                this.isHrUser = await user.hasGroup("hr.group_hr_user");
            });
            this.avatarCard = usePopover(AvatarCardEmployeePopover, {
                closeOnClickAway: true,
            });
        }

        get relation() {
            if (this.props.relation) {
                return this.props.relation;
            }
            return "hr.employee";
        }

        getAvatarCardProps(record) {
            const originalProps = super.getAvatarCardProps(record);
            if (this.relation === "hr.employee") {
                return {
                    ...originalProps,
                    recordModel: this.relation,
                };
            }
            return originalProps;
        }
    };
}
