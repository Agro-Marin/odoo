/** @odoo-module native */
import { ListRenderer } from "@web/views/list/list_renderer";

export class PredecessorIdsListRenderer extends ListRenderer {
    get nbHiddenRecords() {
        // Clamp with the list's total count, not the current page length:
        // next-page records are paginated, not inaccessible.
        const { context, count } = this.props.list;
        return Math.max((context.predecessor_count || 0) - count, 0);
    }
}

PredecessorIdsListRenderer.rowsTemplate = "project.PredecessorIdsListRowsRenderer";
