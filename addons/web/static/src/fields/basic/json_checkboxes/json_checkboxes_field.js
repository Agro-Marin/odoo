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
        // Deep-copied local state: mutating the record's own data object in
        // place would corrupt the discard/rollback baseline (both would share
        // the same reference), and an unset json field reads `false`, which
        // `useState` rejects (reactive() needs an object).
        this.checkboxes = useState(
            deepCopy(this.props.record.data[this.props.name] || {}),
        );
        this.debouncedCommitChanges = useDebounced(this.commitChanges, 100, {
            execBeforeUnmount: true,
        });
        // True while a toggle has been made but its debounced commit hasn't run
        // yet. The model asks every field to flush local changes (via these two
        // buses) before running an onchange or a save; without flushing, an
        // onchange that recomputes this JSON field would be built from the stale
        // record value and the returning server value would silently revert the
        // user's not-yet-committed toggle (see `commitChanges`/observer below).
        this.pendingCommit = false;
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
        });
    }

    /**
     * Writes a copy of the current checkbox state back to the record.
     * @returns {Promise|undefined} the record update, or nothing if no toggle is pending
     */
    commitChanges() {
        if (!this.pendingCommit) {
            return;
        }
        this.pendingCommit = false;
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
        if (!this.pendingCommit) {
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
        this.pendingCommit = true;
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
