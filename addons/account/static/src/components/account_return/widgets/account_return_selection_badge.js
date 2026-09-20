/** @odoo-module native */
import { Component, onWillStart } from "@odoo/owl";
import { Dropdown, DropdownItem } from "@web/components/dropdown";
import { colorScheme } from "@web/core/color_scheme";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class AccountReturnSelectionBadge extends Component {
    static template = "account.AccountReturnSelectionBadgeField";
    static props = {
        ...standardFieldProps,
        decorations: { type: Object, optional: true },
        options: { type: Object, optional: true },
        class: { type: String, optional: true },
        size: { type: String, optional: true },
    };

    setup() {
        onWillStart(async () => {
            this.editableOptions = await this.getEditableOptions();
        });
    }

    static defaultProps = {
        size: "normal",
    };

    static components = {
        Dropdown,
        DropdownItem,
    };

    get options() {
        return this.props.record.fields[this.props.name].selection;
    }

    get value() {
        return this.props.record.data[this.props.name];
    }

    get required() {
        return this.props.record.fields[this.props.name].required;
    }

    get display() {
        const result = this.options.filter((val) => val[0] === this.value)[0];
        if (result) {
            return result[1];
        }
        return null;
    }

    async getEditableOptions() {
        const editableOptions = [false];

        if (
            await user.checkAccessRight(
                this.props.record.resModel,
                "write",
                this.props.record.resId,
            )
        ) {
            for (const [key, value] of Object.entries(this.props.options)) {
                if (
                    [true, undefined].includes(value.can_edit) ||
                    (typeof value.can_edit == "string" &&
                        (await user.hasGroup(value.can_edit)))
                ) {
                    editableOptions.push(key);
                }
            }
        }

        return editableOptions;
    }

    getDropdownButtonDecoration(value) {
        const decoration = this.props.options[value]?.decoration;
        if (!decoration || decoration === "muted") {
            return "btn-outline-secondary";
        }
        return `btn-outline-${decoration}`;
    }

    getDropdownItemDecoration(value) {
        const decoration = this.props.options[value]?.decoration;
        if (decoration) {
            if (decoration === "muted") {
                return colorScheme.isDark ? "text-bg-200" : "text-bg-300";
            }
            return `text-bg-${this.props.options[value].decoration}`;
        }
        return colorScheme.isDark ? "text-bg-200" : "text-bg-100";
    }

    get additionalClassName() {
        const addClasses = [];
        if (this.props.size === "small" || this.env.config?.viewType === "list") {
            addClasses.push("o_account_return_selection_badge_button_small");
        }
        if (this.props.class) {
            addClasses.push(this.props.class);
        }
        return addClasses.join(" ");
    }

    async onChange(value) {
        await this.props.record.update({ [this.props.name]: value }, { save: true });
        this.env.reload?.();
    }
}

export const accountReturnSelectionBadge = {
    supportedTypes: ["selection"],
    component: AccountReturnSelectionBadge,
    extractProps: ({ options }) => ({ options }),
};

registry
    .category("fields")
    .add("account_return_selection_badge", accountReturnSelectionBadge);
