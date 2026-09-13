/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import {
    KanbanController,
    KanbanRecord,
    KanbanRenderer,
    kanbanView,
} from "@web/views/kanban";

import { useLoaderOnClick } from "./theme_preview_form.js";

const log = makeLogger("website.view.theme_preview_kanban");

class ThemePreviewKanbanController extends KanbanController {
    /**
     * @override
     */
    setup() {
        super.setup();
        useLifecycleLog(log);
        useLoaderOnClick();
    }
}

class ThemePreviewControlPanel extends ControlPanel {
    static template = "website.ThemePreviewKanban.ControlPanel";
    setup() {
        super.setup();
        useLifecycleLog(log);
        this.website = useService("website");
    }
    close() {
        log.logic("ThemePreviewControlPanel close: go to website");
        this.website.goToWebsite();
    }
}
class ThemePreviewKanbanrecord extends KanbanRecord {
    /** @override */
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
