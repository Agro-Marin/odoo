// @ts-check
/** @odoo-module native */

import { useState } from "@odoo/owl";
import { _t } from "@web/core/translation";
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

    /** @type {{ displayName: string }} */
    state;

    setup() {
        super.setup();
        this.state = useState({ displayName: "" });
    }

    /** @returns {boolean} */
    get hasAvatarImg() {
        return this.isAvatarModel && isId(this.props.resId);
    }

    /** @returns {string} */
    get displayName() {
        return this.state.displayName;
    }

    /**
     * @param {Record<string, any>} props
     * @param {Record<number, string>} displayNames
     */
    applyDisplayNames(props, displayNames) {
        this.state.displayName = this.getDisplayName(props, displayNames);
    }

    /**
     * @param {Record<string, any>} props
     * @param {Record<number, string>} displayNames
     * @returns {string}
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
     * @param {Record<string, any>} [props]
     * @returns {number[]}
     */
    getIds(props = this.props) {
        if (props.resId) {
            return [props.resId];
        }
        return [];
    }

    /**
     * @param {number[]} resIds
     */
    update(resIds) {
        this.props.update(resIds[0] || false);
    }
}
