// @ts-check
/** @odoo-module native */

/** @module @web/fields/relational/many2many_checkboxes/many2many_checkboxes_field */

import { Component, onWillRender, onWillUnmount, useState } from "@odoo/owl";
import { CheckBox } from "@web/components/checkbox/checkbox";
import { ModelEvent } from "@web/core/events";
import { _t } from "@web/core/translation";
import { useBus } from "@web/core/utils/hooks";
import { debounce } from "@web/core/utils/timing";
import { registerField } from "@web/fields/_registry";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { getFieldDomain } from "@web/model/relational_model/utils";

import { useSpecialData } from "../special_data.js";

export class Many2ManyCheckboxesField extends Component {
    static template = "web.Many2ManyCheckboxesField";
    static RECORD_LIMIT = 100;
    static components = { CheckBox };
    static props = {
        ...standardFieldProps,
        domain: { type: [Array, Function], optional: true },
        context: { type: Object, optional: true },
    };

    setup() {
        this.specialData = useSpecialData(async (orm, props) => {
            const { relation } = props.record.fields[props.name];
            const domain = getFieldDomain(props.record, props.name, props.domain);
            const context = props.context || {};
            const items = await orm.call(relation, "name_search", ["", domain], {
                context,
                limit: /** @type {any} */ (this.constructor).RECORD_LIMIT,
            });
            const shownIds = new Set(items.map((item) => item[0]));
            const missingSelectedIds = props.record.data[props.name].currentIds.filter(
                (id) => !shownIds.has(id),
            );
            if (missingSelectedIds.length) {
                const missing = await orm.call(
                    relation,
                    "name_search",
                    ["", [["id", "in", missingSelectedIds]]],
                    { context },
                );
                return [...items, ...missing];
            }
            return items;
        });
        this.pending = useState({ add: [], remove: [] });
        this.debouncedCommitChanges = debounce(this.commitChanges.bind(this), 500);
        onWillRender(() => {
            this.currentIds = new Set(
                this.props.record.data[this.props.name].currentIds,
            );
        });
        useBus(this.props.record.model.bus, ModelEvent.NEED_LOCAL_CHANGES, (ev) => {
            const result = this.commitChanges();
            if (result) {
                ev.detail.proms.push(result);
            }
        });
        useBus(this.props.record.model.bus, ModelEvent.WILL_SAVE_URGENTLY, (ev) => {
            const result = this.commitChanges();
            if (result) {
                ev.detail?.proms?.push(result);
            }
        });
        onWillUnmount(() => {
            this.debouncedCommitChanges.cancel();
            this.commitChanges();
        });
    }

    /** @returns {Array<[number, string]>} */
    get items() {
        return this.specialData.data;
    }

    /**
     * @param {[number, string]} item
     * @returns {boolean}
     */
    isSelected(item) {
        const id = item[0];
        if (this.pending.remove.includes(id)) {
            return false;
        }
        return this.currentIds.has(id) || this.pending.add.includes(id);
    }

    /** @returns {Promise|undefined} */
    commitChanges() {
        const { add, remove } = this.pending;
        if (!add.length && !remove.length) {
            return;
        }
        const result = this.props.record.data[this.props.name].addAndRemove({
            add: [...add],
            remove: [...remove],
        });
        this.pending.add = [];
        this.pending.remove = [];
        return result;
    }

    /**
     * @param {number} resId
     * @param {boolean} checked
     */
    onChange(resId, checked) {
        const [undo, stage] = checked
            ? [this.pending.remove, this.pending.add]
            : [this.pending.add, this.pending.remove];
        const undoIndex = undo.indexOf(resId);
        if (undoIndex >= 0) {
            undo.splice(undoIndex, 1);
        } else if (!stage.includes(resId)) {
            stage.push(resId);
        }
        this.debouncedCommitChanges();
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const many2ManyCheckboxesField = {
    component: Many2ManyCheckboxesField,
    displayName: _t("Checkboxes"),
    supportedTypes: ["many2many"],
    isEmpty: () => false,
    extractProps(fieldInfo, dynamicInfo) {
        return {
            domain: dynamicInfo.domain,
            context: dynamicInfo.context,
        };
    },
};

registerField("many2many_checkboxes", many2ManyCheckboxesField);
