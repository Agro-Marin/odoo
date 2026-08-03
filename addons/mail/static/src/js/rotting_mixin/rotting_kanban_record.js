/** @odoo-module native */
import { KanbanRecord } from "@web/views/kanban";
export class RottingKanbanRecord extends KanbanRecord {
    /**
     * @override
     */
    getRecordClasses() {
        let classes = super.getRecordClasses();
        if (this.props.record.data.is_rotting) {
            classes += " oe_kanban_card_rotting";
        }
        return classes;
    }
}
