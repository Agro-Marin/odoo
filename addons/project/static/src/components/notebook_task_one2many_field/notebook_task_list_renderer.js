/** @odoo-module native */
import { useState } from "@odoo/owl";

import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";

import { TaskListRenderer } from "../task_list_renderer.js";

export class NotebookTaskListRenderer extends TaskListRenderer {
    static rowsTemplate = "project.NotebookTaskListRenderer.Rows";
    static createControlsTemplate = "project.NotebookTaskListRenderer.CreateControls";
    // Explicit stable key: deriving it from `constructor.name` (as this used
    // to) breaks under minification and silently forks the preference for
    // every subclass.
    static hideClosedStorageKey = "project.notebook_task_list.hide_closed";

    setup() {
        super.setup();
        this.hideState = useState({
            hide:
                browser.localStorage.getItem(this.constructor.hideClosedStorageKey) === "true",
        });
    }

    get hideClosed() {
        return this.hideState.hide;
    }

    get closedX2MCount() {
        return this.props.list.context.closed_X2M_count;
    }

    get openLabel() {
        return typeof this.closedX2MCount === "undefined" ? _t("Show closed tasks") : _t("%s closed tasks", this.closedX2MCount);
    }

    get closeLabel() {
        return _t("Hide closed tasks");
    }

    get toggleListHideLabel() {
        return this.hideClosed ? this.openLabel : this.closeLabel;
    }

    get ShowX2MRecords() {
        // If there isn't a closed_X2M_count defined in the context of the x2m task in the view we are always displaying the Toggle button
        // In case there is no computed field to calculate the number of closed X2M tasks in the backend
        return this.closedX2MCount > 0 || typeof this.closedX2MCount === "undefined";
    }

    toggleHideClosed() {
        this.hideState.hide = !this.hideState.hide;
        browser.localStorage.setItem(this.constructor.hideClosedStorageKey, this.hideState.hide);
        document.activeElement.blur();
    }
}
