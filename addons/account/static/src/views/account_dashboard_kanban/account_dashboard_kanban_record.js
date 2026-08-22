/** @odoo-module native */
import { AccountFileUploader } from "@account/components/account_file_uploader/account_file_uploader";
import { UploadDropZone } from "@account/components/upload_drop_zone/upload_drop_zone";
import { onWillStart, useState } from "@odoo/owl";
import { user } from "@web/core/user";
import { KanbanDropdownMenuWrapper, KanbanRecord } from "@web/views/kanban";

export class DashboardKanbanDropdownMenuWrapper extends KanbanDropdownMenuWrapper {
    onClick(ev) {
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
        this.dashboardState = useState(this.env.dashboardState);
    }

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

    hideDropzone() {
        this.dropzoneState.visible = false;
        this.env.setDragging(false);
    }
}
