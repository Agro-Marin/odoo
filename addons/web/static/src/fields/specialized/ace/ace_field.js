// @ts-check
/** @odoo-module native */

import { useState } from "@odoo/owl";
import { CodeEditor } from "@web/components/code_editor/code_editor";
import { colorScheme } from "@web/core/color_scheme";
import { ModelEvent } from "@web/core/events";
import { formatText } from "@web/core/formatters";
import { _t } from "@web/core/translation";
import { useBus } from "@web/core/utils/hooks";
import { registerField } from "@web/fields/_registry";
import { FieldComponent } from "@web/fields/field_component";
import { useFieldDirtySignal } from "@web/fields/field_dirty_signal";
import { fieldHandleFor } from "@web/fields/field_handle";
import { useRecordObserver } from "@web/fields/hooks/record_observer";
import { standardFieldProps } from "@web/fields/standard_field_props";

export class AceField extends FieldComponent {
    static template = "web.AceField";
    static props = {
        ...standardFieldProps,
        mode: { type: String, optional: true },
    };
    static defaultProps = {
        mode: "qweb",
    };
    static components = { CodeEditor };

    /** @type {ReturnType<typeof useFieldDirtySignal>} */
    setFieldDirty;

    setup() {
        this.state = useState({});
        this.isDirty = false;
        this.setFieldDirty = useFieldDirtySignal();
        useRecordObserver((record) => {
            if (this.editedValue === undefined || !this.isDirty) {
                /** @type {any} */ (this.state).initialValue = formatText(
                    fieldHandleFor(record, this.props.name).value,
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
        return colorScheme.isDark ? "monokai" : "";
    }

    handleChange(editedValue) {
        if (/** @type {any} */ (this.state).initialValue !== editedValue) {
            this.isDirty = true;
        } else {
            this.isDirty = false;
        }
        this.setFieldDirty(this.isDirty);
        this.editedValue = editedValue;
    }

    async commitChanges() {
        if (!this.props.readonly && this.isDirty) {
            if (/** @type {any} */ (this.state).initialValue !== this.editedValue) {
                await this.field.update(this.editedValue);
            }
            this.isDirty = false;
            this.setFieldDirty(false);
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
