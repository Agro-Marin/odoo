// @ts-check
/** @odoo-module native */

import { Component, useEffect, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { useFieldIsDirty } from "@web/views/form/field_is_dirty_hook";

export class FormStatusIndicator extends Component {
    static template = "web.FormStatusIndicator";
    static props = {
        model: Object,
        save: Function,
        discard: Function,
        coordinator: { type: Object, optional: true },
    };

    /** @type {ReturnType<typeof useFieldIsDirty>} */
    hasUnsavedEdits;
    /** @type {import("@odoo/owl").Ref} */
    saveButton;

    setup() {
        this.hasUnsavedEdits = useFieldIsDirty(this.props.model);
        this.coordinator = this.props.coordinator
            ? useState(this.props.coordinator)
            : null;
        this.saveButton = useRef("save");
        useEffect(
            (disabled) => {
                if (!this.saveButton.el) {
                    return;
                }
                if (disabled) {
                    this.saveButton.el.setAttribute("disabled", "1");
                } else {
                    this.saveButton.el.removeAttribute("disabled");
                }
            },
            () => [this.saveButtonDisabled],
        );
    }

    /** @returns {boolean} */
    get displayButtons() {
        return this.indicatorMode !== "saved";
    }

    /** @returns {"dirty" | "invalid" | "saving" | "saved"} */
    get indicatorMode() {
        const { isNew, isValid } = this.props.model.root;
        if (this.coordinator?.isSaving) {
            return "saving";
        }
        const isDirty = this.hasUnsavedEdits() || this.coordinator?.status === "error";
        if (isNew || isDirty) {
            return isValid ? "dirty" : "invalid";
        }
        return "saved";
    }

    /**
     * @returns {boolean}
     */
    get saveButtonDisabled() {
        const { isNew, isValid } = this.props.model.root;
        const isDirty = this.hasUnsavedEdits() || this.coordinator?.status === "error";
        return !isNew && isDirty && !isValid;
    }

    /**
     * @returns {string}
     */
    get statusLabel() {
        switch (this.indicatorMode) {
            case "dirty":
                return _t("Unsaved changes");
            case "invalid":
                return _t("Form has validation errors");
            default:
                return "";
        }
    }

    /** @returns {Promise<void>} */
    async discard() {
        await this.props.discard();
    }
    /** @returns {Promise<void>} */
    async save() {
        await this.props.save();
    }
}
