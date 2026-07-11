// @ts-check
/** @odoo-module native */

/** @module @web/components/record_selectors/record_selector - Single-value record picker with avatar display and autocomplete */

import { useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { isId } from "@web/core/tree/utils";

import { BaseRecordSelector } from "./base_record_selector.js";
import { RecordAutocomplete } from "./record_autocomplete.js";

export class RecordSelector extends BaseRecordSelector {
    static props = {
        resId: [Number, { value: false }],
        resModel: String,
        update: Function,
        domain: { type: Array, optional: true },
        context: { type: Object, optional: true },
        fieldString: { type: String, optional: true },
        placeholder: { type: String, optional: true },
    };
    static components = { RecordAutocomplete };
    static template = "web.RecordSelector";

    setup() {
        super.setup();
        this.state = useState({ displayName: "" });
    }

    /** @returns {boolean} whether the current record should show an avatar */
    get hasAvatarImg() {
        return this.isAvatarModel && isId(this.props.resId);
    }

    /** @returns {string} reactive display name of the selected record */
    get displayName() {
        return this.state.displayName;
    }

    /**
     * @param {Object} props
     * @param {Record<number, string>} displayNames
     */
    applyDisplayNames(props, displayNames) {
        this.state.displayName = this.getDisplayName(props, displayNames);
    }

    /**
     * Resolve the display name for the selected record.
     * @param {Object} props
     * @param {Record<number, string>} displayNames
     * @returns {string} display name or empty string if no record selected
     */
    getDisplayName(props, displayNames) {
        props ??= this.props;
        const { resId } = props;
        if (resId === false) {
            return "";
        }
        return typeof displayNames[resId] === "string"
            ? displayNames[resId]
            : _t("Inaccessible/missing record ID: %s", resId);
    }

    /**
     * @param {Object} [props]
     * @returns {number[]}
     */
    getIds(props = this.props) {
        if (props.resId) {
            return [props.resId];
        }
        return [];
    }

    /**
     * Set the selected record to the first ID in the list, or false if empty.
     * @param {number[]} resIds - selected record IDs from autocomplete
     */
    update(resIds) {
        this.props.update(resIds[0] || false);
    }
}
