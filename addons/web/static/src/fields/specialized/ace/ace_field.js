// @ts-check
/** @odoo-module native */

/** @module @web/fields/specialized/ace/ace_field - Code editor field using the Ace/CodeEditor component */

import { Component, useState } from "@odoo/owl";
import { CodeEditor } from "@web/components/code_editor/code_editor";
import { cookie } from "@web/core/browser/cookie";
import { ModelEvent } from "@web/core/events";
import { _t } from "@web/core/l10n/translation";
import { useBus } from "@web/core/utils/hooks";
import { registerField } from "@web/fields/_registry";
import { formatText } from "@web/fields/formatters";
import { useRecordObserver } from "@web/fields/hooks/record_observer";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class AceField extends Component {
    static template = "web.AceField";
    static props = {
        ...standardFieldProps,
        mode: { type: String, optional: true },
    };
    static defaultProps = {
        mode: "qweb",
    };
    static components = { CodeEditor };

    setup() {
        this.state = useState({});
        this.isDirty = false;
        useRecordObserver((record) => {
            // Guard the rewrite with the widget's dirty state, mirroring
            // useInputField's isDirty protection: an onchange from another field
            // must not re-render the editor to the server value while the user
            // is mid-edit (edits are only committed on blur / urgent-save via
            // editedValue). A clean editor still tracks the incoming value.
            if (this.editedValue === undefined || !this.isDirty) {
                /** @type {any} */ (this.state).initialValue = formatText(
                    record.data[this.props.name],
                );
            }
        });

        const { model } = this.props.record;
        useBus(
            model.bus,
            ModelEvent.WILL_SAVE_URGENTLY,
            /** @type {any} */ ((ev) => ev.detail?.proms?.push(this.commitChanges())),
        );
        useBus(
            model.bus,
            ModelEvent.NEED_LOCAL_CHANGES,
            /** @type {any} */ (
                ({ detail }) => detail.proms.push(this.commitChanges())
            ),
        );
    }

    get mode() {
        return this.props.mode === "xml" ? "qweb" : this.props.mode;
    }
    get theme() {
        return cookie.get("color_scheme") === "dark" ? "monokai" : "";
    }

    handleChange(editedValue) {
        if (/** @type {any} */ (this.state).initialValue !== editedValue) {
            this.isDirty = true;
        } else {
            this.isDirty = false;
        }
        this.props.record.model.bus.trigger(ModelEvent.FIELD_IS_DIRTY, this.isDirty);
        this.editedValue = editedValue;
    }

    async commitChanges() {
        if (!this.props.readonly && this.isDirty) {
            if (/** @type {any} */ (this.state).initialValue !== this.editedValue) {
                await this.props.record.update({
                    [this.props.name]: this.editedValue,
                });
            }
            this.isDirty = false;
            this.props.record.model.bus.trigger(ModelEvent.FIELD_IS_DIRTY, false);
        }
    }
}

export const aceField = {
    component: AceField,
    displayName: _t("Ace Editor"),
    supportedOptions: [
        {
            label: _t("Mode"),
            name: "mode",
            type: "string",
        },
    ],
    supportedTypes: ["text", "html"],
    extractProps: ({ options }) => ({
        mode: options.mode,
    }),
};

registerField({ name: "ace", aliases: ["code"] }, aceField);
