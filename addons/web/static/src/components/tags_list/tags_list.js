// @ts-check
/** @odoo-module native */

/** @module @web/components/tags_list/tags_list */

import { Component } from "@odoo/owl";

export class TagsList extends Component {
    static template = "web.TagsList";
    static defaultProps = {
        displayText: true,
    };
    static props = {
        displayText: { type: Boolean, optional: true },
        visibleItemsLimit: { type: Number, optional: true },
        tags: { type: Array, element: Object },
    };

    /**
     * The last visible slot goes to the "+N" counter, so overflowing shows one
     * fewer tag than the limit.
     *
     * @returns {number}
     */
    get splitIndex() {
        return this.props.visibleItemsLimit - 1;
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
