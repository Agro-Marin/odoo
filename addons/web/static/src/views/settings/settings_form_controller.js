// @ts-check
/** @odoo-module native */

import { useEffect, useRef, useState, useSubEnv } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { useAutofocus } from "@web/core/utils/hooks";
import { formView } from "@web/views/form/form_view";
import { recordResParams } from "@web/views/view_button/view_button";

import { SettingsConfirmationDialog } from "./settings_confirmation_dialog.js";
import { SettingsFormRenderer } from "./settings_form_renderer.js";

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
    /** @param {Record<string, any>} clickParams */
    async beforeExecuteActionButton(clickParams) {
        if (clickParams.name === "cancel") {
            return true;
        }
        if (
            (await this.model.root.isDirty()) &&
            clickParams.name !== "execute" &&
            !clickParams.noSaveDialog
        ) {
            return this._confirmSave();
        } else {
            return this.saveCoordinator.requestSave({ errorMode: "rethrow" });
        }
    }

    displayName() {
        return _t("Settings");
    }

    /** @param {{ forceLeave?: boolean }} [options] */
    async beforeLeave({ forceLeave } = {}) {
        if (forceLeave) {
            return;
        }
        const dirty = await this.model.root.isDirty();
        if (dirty) {
            return this._confirmSave();
        }
    }

    /** @param {any} [_ev] */
    async beforeUnload(_ev) {}

    /** @returns {Promise<any> | undefined} */
    beforeVisibilityChange() {
        return undefined;
    }

    /**
     * @param {any} [_params]
     * @returns {Promise<any>}
     */
    async save(_params) {
        await this.env.onClickViewButton(
            this.viewButtonParams({ name: "execute", type: "object" }),
        );
    }

    async discard() {
        this.env.onClickViewButton(
            this.viewButtonParams({
                name: "cancel",
                type: "object",
                special: "cancel",
            }),
        );
    }

    /** @param {Record<string, any>} clickParams */
    viewButtonParams(clickParams) {
        return { clickParams, getResParams: () => recordResParams(this.model.root) };
    }

    async _confirmSave() {
        let _continue = true;
        await new Promise((resolve) => {
            /** @type {any} */ (this.dialogService).add(SettingsConfirmationDialog, {
                body: _t("Would you like to save your changes?"),
                confirm: async () => {
                    _continue = false;
                    try {
                        await this.save();
                    } finally {
                        resolve();
                    }
                },
                cancel: async () => {
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
                dismiss: () => {
                    _continue = false;
                    resolve();
                },
            });
        });
        return _continue;
    }
}
