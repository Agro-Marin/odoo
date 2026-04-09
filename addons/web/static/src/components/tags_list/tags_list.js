// @ts-check
/** @odoo-module native */

/** @module @web/components/tags_list/tags_list - Renders a list of colored tags with optional visibility limit and overflow counter */

import { Component, useState } from "@odoo/owl";

export class TagsList extends Component {
    static template = "web.TagsList";
    static defaultProps = {
        displayText: true,
    };
    static props = {
        displayText: { type: Boolean, optional: true },
        tagLimit: { type: Number, optional: true },
        // Backward compat alias for tagLimit — prefer tagLimit in new code
        visibleItemsLimit: { type: Number, optional: true },
        tags: { type: Array, element: Object },
    };

    setup() {
        this.state = useState({ expanded: false });
    }

    /** @returns {number | undefined} effective tag limit (tagLimit takes priority) */
    get limit() {
        return this.props.tagLimit ?? this.props.visibleItemsLimit;
    }

    /** @returns {Object[]} tags visible within the limit */
    get visibleTags() {
        const limit = this.limit;
        if (!this.state.expanded && limit && this.props.tags.length > limit) {
            return this.props.tags.slice(0, limit - 1);
        }
        return this.props.tags;
    }

    /** @returns {Object[]} overflow tags hidden behind the "+N" badge */
    get otherTags() {
        const limit = this.limit;
        if (!this.state.expanded && limit && this.props.tags.length > limit) {
            return this.props.tags.slice(limit - 1);
        }
        return [];
    }

    /** @returns {string} JSON-serialized tooltip info for the overflow badge */
    get otherTagsTooltipInfo() {
        return JSON.stringify({ tags: this.otherTags });
    }

    onExpandClick(ev) {
        ev.stopPropagation();
        this.state.expanded = true;
    }
}
