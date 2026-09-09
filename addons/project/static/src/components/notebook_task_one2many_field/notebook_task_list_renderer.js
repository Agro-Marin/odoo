/** @odoo-module native */
import { useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/translation";

import { TaskListRenderer } from "../task_list_renderer.js";

export class NotebookTaskListRenderer extends TaskListRenderer {
    static rowsTemplate = "project.NotebookTaskListRenderer.Rows";
    static createControlsTemplate = "project.NotebookTaskListRenderer.CreateControls";
    static hideClosedStorageKey = "project.notebook_task_list.hide_closed";

    setup() {
        super.setup();
        this.hideState = useState({
            hide:
                browser.localStorage.getItem(this.constructor.hideClosedStorageKey) ===
                "true",
        });
    }

    get hideClosed() {
        return this.hideState.hide;
    }

    get closedX2MCount() {
        return this.props.list.context.closed_X2M_count;
    }

    get openLabel() {
        return typeof this.closedX2MCount === "undefined"
            ? _t("Show closed tasks")
            : _t("%s closed tasks", this.closedX2MCount);
    }

    get closeLabel() {
        return _t("Hide closed tasks");
    }

    get toggleListHideLabel() {
        return this.hideClosed ? this.openLabel : this.closeLabel;
    }

    get ShowX2MRecords() {
        return this.closedX2MCount > 0 || typeof this.closedX2MCount === "undefined";
    }

    toggleHideClosed() {
        this.hideState.hide = !this.hideState.hide;
        browser.localStorage.setItem(
            this.constructor.hideClosedStorageKey,
            this.hideState.hide,
        );
        document.activeElement.blur();
    }
}
