/** @odoo-module native */
import { AccountFileUploader } from "@account/components/account_file_uploader/account_file_uploader";
import { UploadDropZone } from "@account/components/upload_drop_zone/upload_drop_zone";
import { onWillStart, useState } from "@odoo/owl";
import { user } from "@web/core/user";
import { KanbanDropdownMenuWrapper, KanbanRecord } from "@web/views/kanban";

export class DashboardKanbanDropdownMenuWrapper extends KanbanDropdownMenuWrapper {
    onClick(ev) {
        // Keep the dropdown open as we need the fileupload to remain in the dom
        if (
            ev.target.tagName !== "INPUT" &&
            !ev.target.closest(".file_upload_kanban_action_a")
        ) {
            super.onClick(ev);
        }
    }
}

export class DashboardKanbanRecord extends KanbanRecord {
    static template = "account.DashboardKanbanRecord";
    static components = {
        ...KanbanRecord.components,
        UploadDropZone,
        AccountFileUploader,
        KanbanDropdownMenuWrapper: DashboardKanbanDropdownMenuWrapper,
    };

    setup() {
        super.setup();
        onWillStart(async () => {
            const { group } = this.recordDropSettings;
            this.allowDrop = group ? await user.hasGroup(group) : true;
        });
        this.dropzoneState = useState({
            visible: false,
        });
        // Owned by the renderer, which is the only thing that can see a drag
        // enter the kanban at all. The card reads it and passes it down, so the
        // shared dropzone keeps no hidden dependency on this env.
        this.dashboardState = useState(this.env.dashboardState);
    }

    /**
     * The drop settings `_fill_*_dashboard_data` put in `kanban_dashboard`, plus
     * the two company keys that sit beside them.
     *
     * Spread rather than re-list: naming the keys silently dropped the `group`
     * the general-journal branch sends, so the group gating the uploader was
     * never checked. Spreading also tolerates a card that sends no settings.
     */
    get recordDropSettings() {
        const kanbanDashboard = JSON.parse(this.props.record.data.kanban_dashboard);
        return {
            ...kanbanDashboard.drag_drop_settings,
            company_name: kanbanDashboard.company_name,
            show_company: kanbanDashboard.show_company,
        };
    }

    get dropzoneProps() {
        const recordDropSettings = this.recordDropSettings;
        return {
            dragging: this.dashboardState.isDragging,
            visible: this.dropzoneState.visible,
            dragIcon: recordDropSettings.image,
            dragText: recordDropSettings.text,
            dragCompany: recordDropSettings.company_name,
            dragShowCompany: recordDropSettings.show_company,
            dragTitle: this.props.record.data.name,
            hideZone: () => this.hideDropzone(),
        };
    }

    /**
     * Both bits gate the zone, so dismissing it has to clear both — clearing the
     * card's alone left every card's zone up, because the renderer still believed
     * a drag was in flight.
     */
    hideDropzone() {
        this.dropzoneState.visible = false;
        this.env.setDragging(false);
    }
}
