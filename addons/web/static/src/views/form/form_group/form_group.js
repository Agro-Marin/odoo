// @ts-check
/** @odoo-module native */

/** @module @web/views/form/form_group/form_group - OuterGroup and InnerGroup components for form view column layout */

import { Component } from "@odoo/owl";
import { sortBy } from "@web/core/utils/collections/arrays";
/** Base class for form view `<group>` elements, handling slot-based layout. */
class Group extends Component {
    static template = "";
    static props = ["class?", "slots?", "maxCols?", "style?"];
    static defaultProps = {
        maxCols: 2,
    };

    _getItems() {
        const items = Object.entries(this.props.slots || {}).filter(
            ([k, v]) => v.type === "item",
        );
        return sortBy(items, (i) => i[1].sequence);
    }

    getItems() {
        return this._getItems();
    }

    get allClasses() {
        return this.props.class;
    }
}

/** Outer `<group>` — distributes items into Bootstrap columns by their `itemSpan`. */
export class OuterGroup extends Group {
    static template = "web.Form.OuterGroup";
    static defaultProps = {
        ...Group.defaultProps,
        slots: [],
        hasOuterTemplate: true,
    };

    /** @override @returns {any} */
    getItems() {
        const nbCols = this.props.maxCols;
        const colSize = Math.max(1, Math.round(12 / nbCols));

        const items = super
            .getItems()
            .filter(([k, v]) => !("isVisible" in v) || v.isVisible);
        return items.map((item) => {
            const [slotName, slot] = item;
            const itemSpan = slot.itemSpan || 1;
            return {
                name: slotName,
                size: itemSpan * colSize,
                newline: slot.newline,
                colspan: itemSpan,
            };
        });
    }
}

/** Inner `<group>` — distributes items into HTML table rows, respecting `maxCols`. */
export class InnerGroup extends Group {
    static template = "web.Form.InnerGroup";
    getTemplate(subType) {
        const templates = /** @type {any} */ (this.constructor).templates;
        return templates[subType] || templates.default;
    }
    getRows() {
        const maxCols = this.props.maxCols;

        const rows = [];
        let currentRow = [];
        let reservedSpace = 0;

        // Dispatch items across table rows
        const items = this.getItems();
        while (items.length) {
            const [slotName, slot] = items.shift();
            // Same predicate as OuterGroup.getItems: a slot without an
            // isVisible key (third-party form_compilers) is visible —
            // `!slot.isVisible` silently dropped it here.
            if ("isVisible" in slot && !slot.isVisible) {
                continue;
            }

            const { newline, itemSpan } = slot;
            if (newline) {
                rows.push(currentRow);
                currentRow = [];
                reservedSpace = 0;
            }

            const fullItemSpan = itemSpan || 1;

            if (fullItemSpan + reservedSpace > maxCols) {
                rows.push(currentRow);
                currentRow = [];
                reservedSpace = 0;
            }

            currentRow.push({ ...slot, name: slotName, itemSpan, isVisible: true });
            reservedSpace += itemSpan || 1;
        }
        rows.push(currentRow);

        // Every pushed cell is visible (invisible slots were skipped above),
        // so a row renders iff it has cells — empty rows (leading newline,
        // trailing remainder) are dropped by the template's t-if.
        for (const row of rows) {
            /** @type {any} */ (row).isVisible = row.length > 0;
        }

        return rows;
    }
}
