// @ts-check
/** @odoo-module native */

/** @module @web/views/form/form_status_indicator/form_status_indicator - Save/discard indicator shown when the form record is dirty or invalid */

import { Component, useEffect, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useFieldIsDirty } from "@web/views/form/field_is_dirty_hook";

/**
 * Save/discard indicator shown when the form record is dirty or invalid.
 *
 * Combines two signal sources: the ``FIELD_IS_DIRTY`` bus event (fires on raw
 * input before the change is committed, so the indicator reacts while typing)
 * and the optional ``coordinator.status`` (authoritative for saving/error
 * state — see ``form_save_coordinator.js``). ``coordinator`` is optional so
 * embedders outside a full form controller (e.g. knowledge's sidebar
 * indicator) keep working, falling back to the typing signal only.
 */
export class FormStatusIndicator extends Component {
    static template = "web.FormStatusIndicator";
    static props = {
        model: Object,
        save: Function,
        discard: Function,
        coordinator: { type: Object, optional: true },
    };

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

    /** @returns {boolean} whether to show save/discard buttons */
    get displayButtons() {
        return this.indicatorMode !== "saved";
    }

    /** @returns {"dirty" | "invalid" | "saving" | "saved"} current state of the form record */
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
     * Whether the save button should be disabled: an existing record has
     * invalid pending changes (saving would fail validation anyway).
     *
     * Deliberately independent of the save lifecycle (``isSaving``) — that
     * would flip during the window ``executeButtonCallback`` owns the
     * attribute (see the effect in ``setup``), which already handles
     * double-submit protection.
     *
     * @returns {boolean}
     */
    get saveButtonDisabled() {
        const { isNew, isValid } = this.props.model.root;
        const isDirty = this.hasUnsavedEdits() || this.coordinator?.status === "error";
        return !isNew && isDirty && !isValid;
    }

    /**
     * Localized status text for the visually-hidden ``aria-live`` region.
     * Empty for ``saved``/``saving`` so screen readers stay silent on load,
     * after a successful save, or during the (usually sub-second) round-trip.
     *
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
