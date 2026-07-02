// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/json_checkboxes/json_checkboxes_field - Checkbox group field backed by a JSON object of boolean flags */

import { Component, useState } from "@odoo/owl";
import { CheckBox } from "@web/components/checkbox/checkbox";
import { _t } from "@web/core/l10n/translation";
import { useDebounced } from "@web/core/utils/timing";
import { registerField } from "@web/fields/_registry";
import { useRecordObserver } from "@web/fields/hooks/record_observer";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class JsonCheckboxes extends Component {
    static template = "account.JsonCheckboxes";
    static components = { CheckBox };
    static props = {
        ...standardFieldProps,
        stacked: { type: Boolean, optional: true },
    };

    setup() {
        this.checkboxes = useState(this.props.record.data[this.props.name]);
        this.debouncedCommitChanges = useDebounced(this.commitChanges, 100, {
            execBeforeUnmount: true,
        });

        useRecordObserver((record) => {
            Object.assign(this.checkboxes, record.data[this.props.name]);
        });
    }

    /** Writes the current checkbox state back to the record. */
    commitChanges() {
        this.props.record.update({ [this.props.name]: this.checkboxes });
    }

    /**
     * @param {string} key - Checkbox key in the JSON object
     * @param {boolean} checked
     */
    onChange(key, checked) {
        this.checkboxes[key].checked = checked;
        this.debouncedCommitChanges();
    }
}

export const jsonCheckboxes = {
    component: JsonCheckboxes,
    supportedOptions: [
        {
            label: _t("Stacked"),
            name: "stacked",
            type: "boolean",
            help: _t(
                "If checked, the checkboxes will be displayed in a column. Otherwise, they will be inlined.",
            ),
        },
    ],
    supportedTypes: ["json"],
    extractProps({ options }) {
        const stacked = Boolean(options.stacked);
        return {
            stacked,
        };
    },
};

registerField("json_checkboxes", jsonCheckboxes);
