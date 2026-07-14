/** @odoo-module native */
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { PriorityField, priorityField } from "@web/fields/selection/priority/priority_field";

export class PrioritySwitchField extends PriorityField {
    /**
     * Unlike the base "Set priority..." palette command, register one direct
     * command per priority level; alt+r therefore switches straight to the
     * other level (task priority only has two). Keep the base readonly guard:
     * without it the palette/hotkey writes readonly records.
     */
    get commands() {
        return this.options.map(([id, name]) => [
            _t("Set priority as %s", name),
            () => this.updateRecord(id),
            {
                category: "smart_action",
                hotkey: "alt+r",
                isAvailable: () =>
                    !this.props.readonly && this.props.record.data[this.props.name] !== id,
            },
        ]);
    }
}

export const prioritySwitchField = {
    ...priorityField,
    component: PrioritySwitchField,
};

registry.category("fields").add("priority_switch", prioritySwitchField);
