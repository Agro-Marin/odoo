// @ts-check
/** @odoo-module native */

/** @module @web/fields/relational/many2many_checkboxes/many2many_checkboxes_field - Checkbox group field for Many2many relations */

import { Component, onWillRender, onWillUnmount } from "@odoo/owl";
import { CheckBox } from "@web/components/checkbox/checkbox";
import { ModelEvent } from "@web/core/events";
import { _t } from "@web/core/l10n/translation";
import { useBus } from "@web/core/utils/hooks";
import { debounce } from "@web/core/utils/timing";
import { registerField } from "@web/fields/_registry";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { getFieldDomain } from "@web/model/relational_model/utils";

import { useSpecialData } from "../special_data.js";

export class Many2ManyCheckboxesField extends Component {
    static template = "web.Many2ManyCheckboxesField";
    // Upper bound on the pool of checkboxes offered by name_search. Currently
    // selected records beyond this cap are still fetched and rendered (see
    // setup) so they never become impossible to unselect.
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
            const context = this.props.context || {};
            const items = await orm.call(relation, "name_search", ["", domain], {
                context,
                limit: Many2ManyCheckboxesField.RECORD_LIMIT,
            });
            // name_search truncates at RECORD_LIMIT; a currently-selected record
            // past the cutoff would otherwise render no checkbox and become
            // impossible to unselect. Fetch any such records explicitly and
            // append them so every selected value stays manageable. The common
            // case (no overflow) issues no extra RPC.
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
        // these two sets track pending changes in the relation, and allow us to
        // batch consecutive changes into a single replaceWith, thus saving
        // unnecessary potential intermediate onchanges
        this.idsToAdd = new Set();
        this.idsToRemove = new Set();
        this.debouncedCommitChanges = debounce(this.commitChanges.bind(this), 500);
        // `isSelected` is called once per checkbox: build the set of current
        // ids once per render instead of scanning `currentIds` per item.
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

    /** @returns {Array<[number, string]>} Name-search results for available checkboxes */
    get items() {
        return this.specialData.data;
    }

    /**
     * @param {[number, string]} item - A [resId, displayName] pair
     * @returns {boolean}
     */
    isSelected(item) {
        return this.currentIds.has(item[0]);
    }

    /** @returns {Promise|undefined} Flushes pending add/remove changes to the relation */
    commitChanges() {
        if (this.idsToAdd.size === 0 && this.idsToRemove.size === 0) {
            return;
        }
        const result = this.props.record.data[this.props.name].addAndRemove({
            add: [...this.idsToAdd],
            remove: [...this.idsToRemove],
        });
        this.idsToAdd.clear();
        this.idsToRemove.clear();
        return result;
    }

    /**
     * @param {number} resId
     * @param {boolean} checked
     */
    onChange(resId, checked) {
        if (checked) {
            if (this.idsToRemove.has(resId)) {
                this.idsToRemove.delete(resId);
            } else {
                this.idsToAdd.add(resId);
            }
        } else {
            if (this.idsToAdd.has(resId)) {
                this.idsToAdd.delete(resId);
            } else {
                this.idsToRemove.add(resId);
            }
        }
        this.debouncedCommitChanges();
    }
}

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
