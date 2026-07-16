/** @odoo-module native */
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { KanbanRecord } from "@web/views/kanban/kanban_record";
import { KanbanRenderer } from "@web/views/kanban/kanban_renderer";
import { kanbanView } from "@web/views/kanban/kanban_view";

import { useLoaderOnClick } from "./theme_preview_form.js";

class ThemePreviewKanbanController extends KanbanController {
    /**
     * @override
     */
    setup() {
        super.setup();
        useLoaderOnClick();
    }
}

class ThemePreviewControlPanel extends ControlPanel {
    static template = "website.ThemePreviewKanban.ControlPanel";
    setup() {
        super.setup();
        this.website = useService("website");
    }
    close() {
        this.website.goToWebsite();
    }
}
class ThemePreviewKanbanrecord extends KanbanRecord {
    /** @override **/
    getRecordClasses() {
        return super.getRecordClasses() + " p-0 border-0 bg-transparent";
    }
}

export class ThemePreviewKanbanRenderer extends KanbanRenderer {
    static components = {
        ...KanbanRenderer.components,
        KanbanRecord: ThemePreviewKanbanrecord,
    };
}

const ThemePreviewKanbanView = {
    ...kanbanView,
    Controller: ThemePreviewKanbanController,
    ControlPanel: ThemePreviewControlPanel,
    Renderer: ThemePreviewKanbanRenderer,
};

registry.category("views").add("theme_preview_kanban", ThemePreviewKanbanView);
