/** @odoo-module native */
import { patch } from "@web/core/utils/patch";
import { KanbanController } from "@web/views/kanban/kanban_controller";

import { rottingProgressBarPatch } from "./rotting_progress_bar_hook.js";

export class RottingKanbanController extends KanbanController {
    setup() {
        super.setup();
        if (this.progressBarState) {
            // A fresh extension per instance: patch() mutates its argument, so a
            // shared object would throw "already used" on the second render.
            patch(this.progressBarState, rottingProgressBarPatch());
        }
    }

    get progressBarAggregateFields() {
        const res = super.progressBarAggregateFields;
        if (this.props.fields.is_rotting) {
            res.push(this.props.fields.is_rotting);
        }
        return res;
    }
}
