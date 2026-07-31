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

    /** @returns {number} */
    get visibleTagsCount() {
        return this.props.visibleItemsLimit - 1;
    }
    /** @returns {Object[]} */
    get visibleTags() {
        if (
            this.props.visibleItemsLimit &&
            this.props.tags.length > this.props.visibleItemsLimit
        ) {
            return this.props.tags.slice(0, this.visibleTagsCount);
        }
        return this.props.tags;
    }
    /** @returns {Record<string, any>[]} */
    get otherTags() {
        if (
            this.props.visibleItemsLimit &&
            this.props.tags.length > this.props.visibleItemsLimit
        ) {
            return this.props.tags.slice(this.visibleTagsCount);
        }
        return [];
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
