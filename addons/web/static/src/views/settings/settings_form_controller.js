// @ts-check
/** @odoo-module native */

/** @module @web/views/settings/settings_form_controller - Controller for res.config.settings with search filtering and save-via-Apply behavior */

import { useEffect, useRef, useState, useSubEnv } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { pick } from "@web/core/utils/collections/objects";
import { useAutofocus } from "@web/core/utils/hooks";
import { formView } from "@web/views/form/form_view";

import { SettingsConfirmationDialog } from "./settings_confirmation_dialog.js";
import { SettingsFormRenderer } from "./settings_form_renderer.js";

/**
 * Controller for the res.config.settings form view.
 *
 * Adds search-based filtering, confirmation dialogs on unsaved changes,
 * and overrides auto-save behavior (settings should only save via "Apply").
 */
export class SettingsFormController extends formView.Controller {
    static template = "web.SettingsFormView";
    static components = {
        ...formView.Controller.components,
        Renderer: SettingsFormRenderer,
    };

    setup() {
        super.setup();
        useAutofocus();
        this.state = useState({ displayNoContent: false });
        this.searchState = useState({ value: "" });
        this.rootRef = useRef("root");
        this.canCreate = false;
        useSubEnv({ searchState: this.searchState });
        useEffect(
            () => {
                if (this.searchState.value) {
                    // OWL runs effects bottom-up: by the time this controller
                    // effect runs, SettingsApp and SettingsBlock have already
                    // applied their d-none classes for the same search value,
                    // so one selector anchored on non-hidden apps suffices.
                    this.state.displayNoContent = !this.rootRef.el.querySelector(
                        ".app_settings_block:not(.d-none) .o_settings_container:not(.d-none)",
                    );
                } else {
                    this.state.displayNoContent = false;
                }
            },
            () => [this.searchState.value],
        );
        useEffect(
            () => {
                if (this.env.__getLocalState__) {
                    this.env.__getLocalState__.remove(this);
                }
            },
            () => [],
        );

        this.initialApp =
            "module" in this.props.context ? this.props.context.module : "";
    }

    get modelParams() {
        const headerFields = Object.values(this.archInfo.fieldNodes)
            .filter((fieldNode) => fieldNode.options.isHeaderField)
            .map((fieldNode) => fieldNode.name);
        return {
            ...super.modelParams,
            headerFields,
            onChangeHeaderFields: () => this._confirmSave(),
        };
    }

    /**
     * @override
     */
    async beforeExecuteActionButton(clickParams) {
        if (clickParams.name === "cancel") {
            return true;
        }
        if (
            (await this.model.root.isDirty()) &&
            !["execute"].includes(clickParams.name) &&
            !clickParams.noSaveDialog
        ) {
            return this._confirmSave();
        } else {
            // Route through the save coordinator so its observable ``status``
            // reflects settings saves too. ``rethrow`` preserves the historical
            // semantics of the bare ``model.root.save()`` this replaces: errors
            // propagate to ``useViewButtons``' executeButtonCallback.
            return this.saveCoordinator.requestSave({ errorMode: "rethrow" });
        }
    }

    displayName() {
        return _t("Settings");
    }

    /** @param {{ forceLeave?: boolean }} [options] */
    async beforeLeave({ forceLeave } = {}) {
        // Honour ``forceLeave`` like the base FormController: an action that
        // explicitly forces navigation (doAction(..., { forceLeave: true }))
        // must not be blocked by the settings confirmation dialog.
        if (forceLeave) {
            return;
        }
        const dirty = await this.model.root.isDirty();
        if (dirty) {
            return this._confirmSave();
        }
    }

    // Avoid auto-save on unload.
    /** @param {any} [_ev] */
    async beforeUnload(_ev) {}

    // Avoid auto-save on visibility change.
    /** @returns {Promise<any> | undefined} matches the base FormController signature; body intentionally no-op */
    beforeVisibilityChange() {
        return undefined;
    }

    /**
     * @param {any} [_params]
     * @returns {Promise<any>}
     */
    async save(_params) {
        await this.env.onClickViewButton({
            clickParams: {
                name: "execute",
                type: "object",
            },
            getResParams: () =>
                pick(
                    this.model.root,
                    "context",
                    "evalContext",
                    "resModel",
                    "resId",
                    "resIds",
                ),
        });
    }

    async discard() {
        this.env.onClickViewButton({
            clickParams: {
                name: "cancel",
                type: "object",
                special: "cancel",
            },
            getResParams: () =>
                pick(
                    this.model.root,
                    "context",
                    "evalContext",
                    "resModel",
                    "resId",
                    "resIds",
                ),
        });
    }

    async _confirmSave() {
        let _continue = true;
        await new Promise((resolve) => {
            this.dialogService.add(SettingsConfirmationDialog, {
                body: _t("Would you like to save your changes?"),
                confirm: async () => {
                    // The button's action never runs here: on success
                    // res.config.settings.execute triggers a reload; on failure
                    // we stay on the form. Either way ``_continue`` is false.
                    //
                    // try/finally is essential: SettingsConfirmationDialog closes
                    // and RETHROWS when this callback throws, so without settling
                    // in ``finally`` the outer Promise — and every ``beforeLeave``
                    // awaiting it — would hang forever, blocking navigation.
                    _continue = false;
                    try {
                        await this.save();
                    } finally {
                        resolve();
                    }
                },
                cancel: async () => {
                    // Discard the pending edits, then persist the reverted values
                    // via the coordinator so the button's action runs against a
                    // saved record and ``status`` stays accurate. As above, always
                    // resolve() so a discard-then-save failure can't hang the
                    // promise; on failure ``_continue`` stays false.
                    _continue = false;
                    try {
                        await this.saveCoordinator.requestDiscard();
                        await this.saveCoordinator.requestSave({
                            errorMode: "rethrow",
                        });
                        _continue = true;
                    } finally {
                        resolve();
                    }
                },
                stayHere: () => {
                    _continue = false;
                    resolve();
                },
            });
        });
        return _continue;
    }
}
