/** @odoo-module native */
import { useService } from "@web/core/utils/hooks";
import { useLayoutEffect } from "@web/core/utils/layout_effect";
import { ListRenderer } from "@web/views/list";

export class TaskListRenderer extends ListRenderer {
    setup() {
        super.setup();
        this.dialog = useService("dialog");
        useLayoutEffect(
            (editedRecord) => this.focusName(editedRecord),
            () => [this.editedRecord],
        );
    }

    focusName(editedRecord) {
        if (editedRecord?.isNew && !editedRecord.dirty) {
            const col = this.columns.find((c) => c.name === "name");
            this.focusCell(col);
        }
    }
}
