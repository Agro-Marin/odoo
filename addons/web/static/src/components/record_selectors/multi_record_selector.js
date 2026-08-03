// @ts-check
/** @odoo-module native */

/** @module @web/components/record_selectors/multi_record_selector */

import { useState } from "@odoo/owl";
import { TagsList } from "@web/components/tags_list/tags_list";
import { _t } from "@web/core/translation";
import { isId } from "@web/core/tree/utils";
import { imageUrl } from "@web/core/utils/urls";

import { BaseRecordSelector } from "./base_record_selector.js";
import { RecordAutocomplete } from "./record_autocomplete.js";
import { useTagNavigation } from "./tag_navigation_hook.js";

/** @typedef {{ text: string, onDelete: Function, img: string | false }} RecordTag */
/** @typedef {{ resIds: number[], [key: string]: any }} MultiRecordSelectorProps */

export class MultiRecordSelector extends BaseRecordSelector {
    static props = {
        resIds: { type: Array, element: Number },
        resModel: String,
        update: Function,
        domain: { type: Array, optional: true },
        context: { type: Object, optional: true },
        fieldString: { type: String, optional: true },
        placeholder: { type: String, optional: true },
    };
    static components = { RecordAutocomplete, TagsList };
    static template = "web.MultiRecordSelector";

    /** @type {{ tags: RecordTag[] }} */
    state;

    setup() {
        super.setup();
        this.state = useState({ tags: [] });
        useTagNavigation("multiRecordSelector", {
            delete: (index) => this.deleteTag(index),
        });
    }

    /** @returns {RecordTag[]} */
    get tags() {
        return this.state.tags;
    }

    /**
     * @param {MultiRecordSelectorProps} props
     * @param {Record<number, string>} displayNames
     */
    applyDisplayNames(props, displayNames) {
        this.state.tags = this.getTags(props, displayNames);
    }

    /**
     * @returns {string | undefined}
     */
    get placeholder() {
        return this.props.resIds.length ? "" : this.props.placeholder;
    }

    /**
     * @param {MultiRecordSelectorProps} [props]
     * @returns {number[]}
     */
    getIds(props = this.props) {
        return props.resIds;
    }

    /**
     * @param {MultiRecordSelectorProps} props
     * @param {Record<number, string>} displayNames
     * @returns {RecordTag[]}
     */
    getTags(props, displayNames) {
        return props.resIds.map((id, index) => {
            const text =
                typeof displayNames[id] === "string"
                    ? displayNames[id]
                    : _t("Inaccessible/missing record ID: %s", id);
            return {
                text,
                onDelete: () => {
                    this.deleteTag(index);
                },
                img:
                    this.isAvatarModel &&
                    isId(id) &&
                    imageUrl(this.props.resModel, id, "avatar_128"),
            };
        });
    }

    /**
     * @param {number} index
     */
    deleteTag(index) {
        this.props.update([
            ...this.props.resIds.slice(0, index),
            ...this.props.resIds.slice(index + 1),
        ]);
    }

    /**
     * @param {number[]} resIds
     */
    update(resIds) {
        this.props.update([...this.props.resIds, ...resIds]);
    }
}
