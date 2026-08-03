/** @odoo-module native */
import { KanbanArchParser } from "@web/views/kanban";

export class DocumentsKanbanArchParser extends KanbanArchParser {
    parse(xmlDoc, models, modelName) {
        const archInfo = super.parse(xmlDoc, models, modelName);
        archInfo.canOpenRecords = false;
        return archInfo;
    }
}
