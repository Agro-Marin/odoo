// @ts-check
/** @odoo-module native */

/** @module @web/fields/basic/json_checkboxes/json_checkboxes_field - Checkbox group field backed by a JSON object of boolean flags */

import { Component, useState } from "@odoo/owl";
import { CheckBox } from "@web/components/checkbox/checkbox";
import { ModelEvent } from "@web/core/events";
import { _t } from "@web/core/l10n/translation";
import { deepCopy } from "@web/core/utils/collections/objects";
import { useBus } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { registerField } from "@web/fields/_registry";
import { useRecordObserver } from "@web/fields/hooks/record_observer";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class JsonCheckboxes extends Component {
    static template = "web.JsonCheckboxes";
    static components = { CheckBox };
    static props = {
        ...standardFieldProps,
        stacked: { type: Boolean, optional: true },
    };

    setup() {
        this.checkboxes = useState(
            deepCopy(this.props.record.data[this.props.name] || {}),
        );
        this.debouncedCommitChanges = useDebounced(this.commitChanges, 100, {
            execBeforeUnmount: true,
        });
        /**
         * Toggles the user has made that have not reached the record yet, as
         * ``key -> checked``.
         *
         * A plain "something is pending" boolean was not enough. A click is
         * only written to the record 100ms later, and any model patch arriving
         * inside that window — an onchange on a NEIGHBOURING field is the
         * ordinary case — re-ran the observer below, which assigned the
         * record's value straight over the local state. The click was gone from
         * the UI, and the debounced commit then wrote the clobbered state back:
         * a silently discarded edit, with no error anywhere. Knowing WHICH keys
         * are pending is what lets the incoming value stay authoritative for
         * everything else.
         *
         * @type {Map<string, boolean>}
         */
        this.pendingToggles = new Map();
        useBus(this.props.record.model.bus, ModelEvent.NEED_LOCAL_CHANGES, (ev) => {
            this.flushPendingCommit(ev);
        });
        useBus(this.props.record.model.bus, ModelEvent.WILL_SAVE_URGENTLY, (ev) => {
            this.flushPendingCommit(ev);
        });

        useRecordObserver((record) => {
            const value = deepCopy(record.data[this.props.name] || {});
            for (const key of Object.keys(this.checkboxes)) {
                if (!(key in value)) {
                    delete this.checkboxes[key];
                }
            }
            Object.assign(this.checkboxes, value);
            for (const [key, checked] of this.pendingToggles) {
                if (key in this.checkboxes) {
                    this.checkboxes[key].checked = checked;
                } else {
                    // The incoming value dropped the key entirely; there is
                    // nothing left to re-apply it to.
                    this.pendingToggles.delete(key);
                }
            }
        });
    }

    /**
     * Writes a copy of the current checkbox state back to the record.
     * @returns {Promise|undefined} the record update, or nothing if no toggle is pending
     */
    commitChanges() {
        if (!this.pendingToggles.size) {
            return;
        }
        this.pendingToggles.clear();
        return this.props.record.update({
            [this.props.name]: deepCopy(this.checkboxes),
        });
    }

    /**
     * Synchronously flush the debounced commit so a pending toggle reaches the
     * record before the model runs an onchange/save, then hand the resulting
     * update promise to the model so it waits for it.
     * @param {CustomEvent} ev
     */
    flushPendingCommit(ev) {
        if (!this.pendingToggles.size) {
            return;
        }
        this.debouncedCommitChanges.cancel();
        const result = this.commitChanges();
        if (result) {
            ev.detail?.proms?.push(result);
        }
    }

    /**
     * @param {string} key - Checkbox key in the JSON object
     * @param {boolean} checked
     */
    onChange(key, checked) {
        this.checkboxes[key].checked = checked;
        this.pendingToggles.set(key, checked);
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
