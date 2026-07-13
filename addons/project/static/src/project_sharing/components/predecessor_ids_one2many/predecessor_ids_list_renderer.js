/** @odoo-module native */
import { ListRenderer } from "@web/views/list/list_renderer";

export class PredecessorIdsListRenderer extends ListRenderer {
    get nbHiddenRecords() {
        const { context, records } = this.props.list;
        return (context.predecessor_count || 0) - records.length;
    }
}

PredecessorIdsListRenderer.rowsTemplate = "project.PredecessorIdsListRowsRenderer";
