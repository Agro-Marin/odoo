// @ts-check
/** @odoo-module native */

/** @module @web/components/record_selectors/multi_record_selector - Multi-value record picker with tag display and autocomplete search */

import { TagsList } from "@web/components/tags_list/tags_list";
import { _t } from "@web/core/l10n/translation";
import { isId } from "@web/core/tree/utils";
import { imageUrl } from "@web/core/utils/urls";

import { BaseRecordSelector } from "./base_record_selector.js";
import { RecordAutocomplete } from "./record_autocomplete.js";
import { useTagNavigation } from "./tag_navigation_hook.js";

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

    setup() {
        super.setup();
        useTagNavigation("multiRecordSelector", {
            delete: (index) => this.deleteTag(index),
        });
    }

    /**
     * @param {Object} props
     * @param {Record<number, string>} displayNames
     */
    applyDisplayNames(props, displayNames) {
        this.tags = this.getTags(props, displayNames);
    }

    /**
     * Empty when at least one tag exists — the input itself stays empty even
     * with tags, so the native placeholder attribute can't be relied on.
     * @returns {string | undefined}
     */
    get placeholder() {
        return this.props.resIds.length ? "" : this.props.placeholder;
    }

    /**
     * @param {Object} [props]
     * @returns {number[]}
     */
    getIds(props = this.props) {
        return props.resIds;
    }

    /**
     * Build tag objects from record IDs and their display names.
     * @param {Object} props
     * @param {Record<number, string>} displayNames
     * @returns {Array<{text: string, onDelete: Function, img: string | false}>}
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
     * Remove a tag by index and notify the parent.
     * @param {number} index - position of the tag to remove
     */
    deleteTag(index) {
        this.props.update([
            ...this.props.resIds.slice(0, index),
            ...this.props.resIds.slice(index + 1),
        ]);
    }

    /**
     * Append newly selected record IDs to the current selection.
     * @param {number[]} resIds - IDs to add
     */
    update(resIds) {
        this.props.update([...this.props.resIds, ...resIds]);
    }
}
