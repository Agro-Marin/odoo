// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { useRenderCounter } from "@web/core/utils/render_instrumentation";

/**
 * @typedef {Object} Tag
 * @property {string|number} [id]
 * @property {string} [text]
 * @property {string} [title]
 * @property {string} [img]
 * @property {string} [imageClass]
 * @property {string} [icon]
 * @property {string} [className]
 * @property {number} [colorIndex]
 * @property {boolean} [canEdit]
 * @property {(ev: MouseEvent) => any} [onClick]
 * @property {(ev: MouseEvent) => any} [onDelete]
 */
const TAG_SHAPE = {
    type: Object,
    shape: {
        id: { type: [String, Number], optional: true },
        text: { type: String, optional: true },
        title: { type: String, optional: true },
        img: { type: [String, Boolean], optional: true },
        imageClass: { type: String, optional: true },
        icon: { type: String, optional: true },
        className: { type: String, optional: true },
        colorIndex: { type: Number, optional: true },
        canEdit: { type: Boolean, optional: true },
        onClick: { type: Function, optional: true },
        onDelete: { type: Function, optional: true },
        "*": true,
    },
};

export class TagsList extends Component {
    static template = "web.TagsList";
    static defaultProps = {
        displayText: true,
    };
    static props = {
        displayText: { type: Boolean, optional: true },
        visibleItemsLimit: { type: Number, optional: true },
        tags: { type: Array, element: TAG_SHAPE },
    };

    setup() {
        useRenderCounter("components.TagsList");
    }

    /**
     * `resId` first, because `id` is not stable for every producer: the x2many
     * tag builders fill it with the relational model's *datapoint* id, which is
     * re-minted whenever the list reloads. Keying on that made an unrelated save
     * destroy and rebuild every tag's DOM node -- losing focus, selection and any
     * running transition -- although nothing about the tag had changed.
     *
     * `||` rather than `??` on purpose: an unsaved record has `resId === false`,
     * which must fall through to the datapoint id rather than key every such tag
     * the same.
     *
     * @param {Tag} tag
     * @param {number} index
     * @returns {string | number}
     */
    tagKey(tag, index) {
        return /** @type {any} */ (tag).resId || tag.id || index;
    }

    /**
     * @returns {number}
     */
    get splitIndex() {
        return this.props.visibleItemsLimit ? this.props.visibleItemsLimit - 1 : 0;
    }
    /** @returns {boolean} */
    get hasOverflow() {
        return Boolean(
            this.props.visibleItemsLimit &&
            this.props.tags.length > this.props.visibleItemsLimit,
        );
    }
    /** @returns {Object[]} */
    get visibleTags() {
        return this.hasOverflow
            ? this.props.tags.slice(0, this.splitIndex)
            : this.props.tags;
    }
    /** @returns {Record<string, any>[]} */
    get otherTags() {
        return this.hasOverflow ? this.props.tags.slice(this.splitIndex) : [];
    }
    /** @returns {string} */
    get tooltipInfo() {
        return JSON.stringify({
            tags: this.otherTags.map((tag) => ({
                text: tag.text,
                id: tag.id,
            })),
        });
    }
}
