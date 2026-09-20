/** @odoo-module native */
import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/ui/dialog";

/**
 * Which occurrences of a recurrence an edit applies to.
 *
 * `calendar` and `planning` each carried their own copy of this component and
 * of its template, identical but for the dialog title and the three labels --
 * the vocabulary, which is the only part that is genuinely per-model. That part
 * is a prop here; the mechanism is not duplicated.
 */
export class AskRecurrenceUpdateDialog extends Component {
    static template = "resource.AskRecurrenceUpdateDialog";
    static components = { Dialog };
    static props = {
        title: String,
        // Ordered {value: label}; the first entry is the default.
        choices: Object,
        confirm: Function,
        close: Function,
    };

    setup() {
        this.state = useState({ selected: Object.keys(this.props.choices)[0] });
    }

    confirm() {
        this.props.confirm(this.state.selected);
        this.props.close();
    }
}

export function askRecurrenceUpdate(dialogService, { title, choices }) {
    return new Promise((resolve) => {
        dialogService.add(
            AskRecurrenceUpdateDialog,
            { title, choices, confirm: resolve },
            { onClose: resolve.bind(null, false) },
        );
    });
}
