// @ts-check
/** @odoo-module native */

import { isAvatarModel } from "@web/components/record_selectors/avatar_models";
import { MultiRecordSelector } from "@web/components/record_selectors/multi_record_selector";
import { RecordSelector } from "@web/components/record_selectors/record_selector";
import { formatAST } from "@web/core/py_js/py";
import { toPyValue } from "@web/core/py_js/py_utils";
import { _t } from "@web/core/translation";
import { Expression } from "@web/core/tree/condition_tree";
import { isId } from "@web/core/tree/utils";
import { imageUrl } from "@web/core/utils/urls";

/** @typedef {{ resIds: any[], [key: string]: any }} DomainSelectorMultiProps */
/** @typedef {{ resId: any, [key: string]: any }} DomainSelectorSingleProps */

/**
 * @param {number|import("@web/core/tree/condition_tree").Expression|any} val
 * @param {Record<number, string>} displayNames
 * @returns {{text: string, colorIndex: number}}
 */
const getFormat = (val, displayNames) => {
    let text;
    let colorIndex;
    if (isId(val)) {
        text =
            typeof displayNames[val] === "string"
                ? displayNames[val]
                : _t("Inaccessible/missing record ID: %s", val);
        colorIndex = typeof displayNames[val] === "string" ? 0 : 2;
    } else {
        text =
            val instanceof Expression
                ? String(val)
                : _t("Invalid record ID: %s", formatAST(toPyValue(val)));
        colorIndex = val instanceof Expression ? 2 : 1;
    }
    return { text, colorIndex };
};

// The base declares `resIds` as `{ type: Array, element: Number }`; here it
// also holds `Expression`s, which is what widening it to `true` says. Owl's
// props schema is not a type, so the static sides genuinely differ and the
// checker is right to say so.
// @ts-expect-error - OWL Component static props typing
export class DomainSelectorAutocomplete extends MultiRecordSelector {
    static props = {
        ...MultiRecordSelector.props,
        resIds: true,
    };

    /**
     * @param {DomainSelectorMultiProps} [props]
     * @returns {number[]}
     */
    getIds(props = this.props) {
        return props.resIds.filter((val) => isId(val));
    }

    /**
     * @param {DomainSelectorMultiProps} props
     * @param {Record<number, string>} displayNames
     * @returns {import("@web/components/record_selectors/multi_record_selector").RecordTag[]}
     */
    getTags(props, displayNames) {
        const withAvatar = isAvatarModel(props.resModel);
        return props.resIds.map((val, index) => {
            const { text, colorIndex } = getFormat(val, displayNames);
            return {
                text,
                colorIndex,
                onDelete: () => {
                    this.props.update([
                        ...this.props.resIds.slice(0, index),
                        ...this.props.resIds.slice(index + 1),
                    ]);
                },
                img:
                    withAvatar &&
                    isId(val) &&
                    imageUrl(props.resModel, val, "avatar_128"),
            };
        });
    }
}

// @ts-expect-error - OWL Component static props typing
export class DomainSelectorSingleAutocomplete extends RecordSelector {
    static props = {
        ...RecordSelector.props,
        resId: true,
    };

    /**
     * @param {DomainSelectorSingleProps} props
     * @param {Record<number, string>} displayNames
     * @returns {string}
     */
    getDisplayName(props, displayNames) {
        const { resId } = props;
        if (resId === false) {
            return "";
        }
        const { text } = getFormat(resId, displayNames);
        return text;
    }

    /**
     * @param {DomainSelectorSingleProps} [props]
     * @returns {number[]}
     */
    getIds(props = this.props) {
        if (isId(props.resId)) {
            return [props.resId];
        }
        return [];
    }
}
