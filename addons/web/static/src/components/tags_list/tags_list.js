// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";

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
