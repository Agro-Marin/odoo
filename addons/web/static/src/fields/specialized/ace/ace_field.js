// @ts-check
/** @odoo-module native */

import { useState } from "@odoo/owl";
import { CodeEditor } from "@web/components/code_editor/code_editor";
import { colorScheme } from "@web/core/color_scheme";
import { formatText } from "@web/core/formatters";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { registerField } from "@web/fields/_registry";
import { FieldComponent } from "@web/fields/field_component";
import { useFieldDirtySignal } from "@web/fields/field_dirty_signal";
import { fieldHandleFor } from "@web/fields/field_handle";
import { useFieldFlush } from "@web/fields/hooks/debounced_field_commit";
import { useRecordObserver } from "@web/fields/hooks/record_observer";
import { standardFieldProps } from "@web/fields/standard_field_props";

const JSON_INDENT = 2;

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
        this.notification = useService("notification");
        useRecordObserver((record) => {
            if (this.editedValue === undefined || !this.isDirty) {
                /** @type {any} */ (this.state).initialValue = this.serialize(
                    fieldHandleFor(record, this.props.name).value,
                );
            }
        });

        useFieldFlush(this.props.record.model.bus, (ev) =>
            ev.detail?.proms?.push(this.commitChanges()),
        );
    }

    get mode() {
        return this.props.mode === "xml" ? "qweb" : this.props.mode;
    }
    get theme() {
        return colorScheme.isDark ? "monokai" : "";
    }
    /** @returns {boolean} */
    get isJson() {
        return this.field.definition.type === "json";
    }

    /**
     * @param {any} value
     * @returns {string}
     */
    serialize(value) {
        if (!this.isJson) {
            return formatText(value);
        }
        return value === false || value === undefined
            ? ""
            : JSON.stringify(value, null, JSON_INDENT);
    }

    /**
     * @param {string} text
     * @returns {any}
     * @throws {SyntaxError}
     */
    deserialize(text) {
        if (!this.isJson) {
            return text;
        }
        return text.trim() ? JSON.parse(text) : false;
    }

    handleChange(editedValue) {
        if (/** @type {any} */ (this.state).initialValue !== editedValue) {
            this.isDirty = true;
        } else {
            this.isDirty = false;
        }
        this.setFieldDirty(this.isDirty);
        this.editedValue = editedValue;
        if (this.props.record.invalidFields.has(this.props.name)) {
            // an edit reopens the save; the next commit decides again
            this.props.record.resetFieldValidity(this.props.name);
        }
    }

    async commitChanges() {
        if (!this.props.readonly && this.isDirty) {
            if (/** @type {any} */ (this.state).initialValue !== this.editedValue) {
                let value;
                try {
                    value = this.deserialize(this.editedValue);
                } catch {
                    this.props.record.setInvalidField(this.props.name);
                    this.notification.add(
                        _t("Invalid JSON: your changes to this field were not saved."),
                        { type: "danger" },
                    );
                    return;
                }
                await this.field.update(value);
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
    supportedTypes: ["text", "html", "json"],
    extractProps: ({ options }) => ({
        mode: options.mode,
    }),
};

registerField({ name: "ace", aliases: ["code"] }, aceField);
