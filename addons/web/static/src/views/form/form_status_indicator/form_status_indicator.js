// @ts-check
/** @odoo-module native */

/** @module @web/views/form/form_status_indicator/form_status_indicator - Save/discard indicator shown when the form record is dirty or invalid */

import { Component, useEffect, useRef, useState } from "@odoo/owl";
import { ModelEvent } from "@web/core/events";
import { _t } from "@web/core/l10n/translation";
import { useBus } from "@web/core/utils/hooks";

/**
 * Save/discard indicator shown in the form view when the record is dirty or
 * invalid.
 *
 * Two-source state design (both sources are needed, they observe different
 * phases of an edit):
 *
 *   - **Typing signal** — the ``FIELD_IS_DIRTY`` model bus event +
 *     ``model.root.dirty``.  Fields fire ``FIELD_IS_DIRTY`` on raw input,
 *     *before* the change is committed to the record (commit happens on
 *     blur/urgent-save).  This is what makes the indicator react while the
 *     user is still typing.  The save coordinator cannot provide this: it
 *     only observes committed changes through its save/discard entry points.
 *
 *   - **Lifecycle signal** — ``coordinator.status``
 *     (``"clean" | "dirty" | "saving" | "error"``, see
 *     ``form_save_coordinator.js``).  The coordinator is the authority on
 *     the save lifecycle: whether a save is in flight (``isSaving``) and
 *     whether the last save failed (``status === "error"`` /
 *     ``lastError``).  The indicator derives its ``saving`` display mode
 *     and its post-failure dirty display from it instead of
 *     reverse-engineering them from scattered flags.
 *
 * The ``coordinator`` prop is optional so embedders that reuse the component
 * outside a full form controller (e.g. knowledge's hierarchy sidebar
 * indicator) keep working; without it the indicator falls back to the
 * typing signal only, which was the historical behavior.
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
        this.state = useState({
            fieldIsDirty: false,
        });
        // Subscribe this component to the coordinator's reactive state
        // (FormSaveCoordinator extends SignalStore, so the instance is
        // already a reactive proxy; useState re-wraps it with this
        // component's render callback as observer).
        this.coordinator = this.props.coordinator
            ? useState(this.props.coordinator)
            : null;
        useBus(
            this.props.model.bus,
            ModelEvent.FIELD_IS_DIRTY,
            (ev) => (this.state.fieldIsDirty = ev.detail),
        );
        this.saveButton = useRef("save");
        // The save button's ``disabled`` attribute is managed imperatively
        // (not via a ``t-att-disabled`` template binding) on purpose:
        // ``executeButtonCallback`` (view_button_hook.js) bulk-disables all
        // enabled buttons with ``setAttribute("disabled")`` while an
        // action/save runs and re-enables them after.  An OWL-bound
        // attribute is reset to its bound value on *every* re-render of
        // this component — and this component re-renders during saves by
        // design (it observes ``coordinator.status``) — which would strip
        // the imperatively-set attribute mid-action.  The effect below
        // only touches the attribute when ``saveButtonDisabled`` actually
        // changes, so it coexists with the bulk-disable.
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
        const isDirty =
            this.props.model.root.dirty ||
            this.state.fieldIsDirty ||
            // A save that raised an unhandled error leaves the record dirty;
            // the coordinator's status is the authoritative signal for it.
            this.coordinator?.status === "error";
        if (isNew || isDirty) {
            return isValid ? "dirty" : "invalid";
        }
        return "saved";
    }

    /**
     * Whether the save button should be disabled: an existing record has
     * invalid pending changes (saving would fail validation anyway).
     *
     * Deliberately independent of the save lifecycle (``isSaving``): a
     * lifecycle-dependent value would flip during the exact window in
     * which ``executeButtonCallback`` owns the attribute (see the effect
     * in ``setup``), and double-submit protection is already owned by
     * ``executeButtonCallback``.
     *
     * @returns {boolean}
     */
    get saveButtonDisabled() {
        const { isNew, isValid } = this.props.model.root;
        const isDirty =
            this.props.model.root.dirty ||
            this.state.fieldIsDirty ||
            this.coordinator?.status === "error";
        return !isNew && isDirty && !isValid;
    }

    /**
     * Localized status text consumed by the visually-hidden ``aria-live``
     * region in the template.  Returns an empty string for the ``saved``
     * and ``saving`` modes so screen readers do not announce anything on
     * initial load, after a successful save, or during the (usually
     * sub-second) save round-trip — the polite live region only speaks up
     * when the user needs to know about an open commitment or a problem.
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
