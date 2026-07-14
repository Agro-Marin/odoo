/** @odoo-module native */
import { Component, useState, useRef } from "@odoo/owl";

import { _t } from "@web/core/l10n/translation";
import { useAutofocus } from "@web/core/utils/hooks";

export class SubtaskCreate extends Component {
    static template = "project.SubtaskCreate";
    static props = {
        name: String,
        onSubtaskCreateNameChanged: { type: Function },
        onBlur: { type: Function },
    };
    setup() {
        this.placeholder = _t("Write a task name");
        this.state = useState({
            name: this.props.name,
            isFieldInvalid: false,
        });
        this.input = useRef("subtaskCreateInput");
        useAutofocus({ refName: "subtaskCreateInput" });
    }

    /**
     * Close the create row when focus leaves the component (click-away),
     * matching the kanban quick-create UX. The `change` event fired just
     * before this one, so a typed name has already been submitted.
     *
     * @private
     * @param {FocusEvent} ev
     */
    _onBlur(ev) {
        if (ev.relatedTarget?.closest(".subtask_create_input")) {
            // Focus moved inside the component (e.g. onto the SAVE button).
            return;
        }
        this.props.onBlur();
    }

    /**
     * @private
     * @param {InputEvent} ev
     */
    _onInput(ev) {
        const value = ev.target.value;
        this.state.name = value;
        this.state.isFieldInvalid = false;
    }

    _onClick() {
        this.input.el.focus();
    }

    /**
     * @private
     * @param {InputEvent} ev
     */
    _onNameChanged(ev) {
        const value = ev.target.value.trim();
        if (value !== "") {
            this.props.onSubtaskCreateNameChanged(value);
            ev.target.blur();
        }
    }

    _onSaveClick() {
        // Only the empty case needs handling: pressing SAVE with a non-empty
        // name already blurred the input, whose `change` event submitted it
        // (submitting again here would create the subtask twice).
        if (this.input.el.value.trim() === "") {
            this.props.onSubtaskCreateNameChanged(this.input.el.value.trim());
            this.state.isFieldInvalid = true;
            this.state.name = "";
        }
    }
}
