/** @odoo-module native */
import { ListRenderer } from "@web/views/list";

export class PredecessorIdsListRenderer extends ListRenderer {
    get nbHiddenRecords() {
        const { context, count } = this.props.list;
        return Math.max((context.predecessor_count || 0) - count, 0);
    }
}

PredecessorIdsListRenderer.rowsTemplate = "project.PredecessorIdsListRowsRenderer";
