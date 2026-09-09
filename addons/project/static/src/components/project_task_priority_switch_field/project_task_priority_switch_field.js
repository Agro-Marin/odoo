/** @odoo-module native */
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import {
    PriorityField,
    priorityField,
} from "@web/fields/selection/priority/priority_field";

export class PrioritySwitchField extends PriorityField {
    get commands() {
        return this.options.map(([id, name]) => [
            _t("Set priority as %s", name),
            () => this.updateRecord(id),
            {
                category: "smart_action",
                hotkey: "alt+r",
                isAvailable: () =>
                    !this.props.readonly &&
                    this.props.record.data[this.props.name] !== id,
            },
        ]);
    }
}

export const prioritySwitchField = {
    ...priorityField,
    component: PrioritySwitchField,
};

registry.category("fields").add("priority_switch", prioritySwitchField);
