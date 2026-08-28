// @ts-check
/** @odoo-module native */

import { useState } from "@odoo/owl";
import { isAvatarModel } from "@web/components/record_selectors/avatar_models";
import { TagsList } from "@web/components/tags_list/tags_list";
import { isId } from "@web/core/tree/utils";
import { imageUrl } from "@web/core/utils/urls";

import { BaseRecordSelector, displayNameFor } from "./base_record_selector.js";
import { RecordAutocomplete } from "./record_autocomplete.js";
import { useTagNavigation } from "./tag_navigation_hook.js";

/**
 * @typedef {{ id?: number, text: string, onDelete: Function, img: string | false,
 * colorIndex?: number }} RecordTag
 */
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
            delete: (index) => this.deleteTagAt(index),
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
        const withAvatar = isAvatarModel(props.resModel);
        return props.resIds.map((id) => ({
            id,
            text: displayNameFor(displayNames, id),
            onDelete: () => {
                this.deleteTag(id);
            },
            img: withAvatar && isId(id) && imageUrl(props.resModel, id, "avatar_128"),
        }));
    }

    /**
     * @param {number} resId
     */
    deleteTag(resId) {
        const props = /** @type {MultiRecordSelectorProps} */ (this.props);
        props.update(props.resIds.filter((id) => id !== resId));
    }

    /**
     * @param {number} index
     */
    deleteTagAt(index) {
        this.state.tags[index]?.onDelete();
    }

    /**
     * @param {number[]} resIds
     */
    update(resIds) {
        this.props.update([...this.props.resIds, ...resIds]);
    }
}
