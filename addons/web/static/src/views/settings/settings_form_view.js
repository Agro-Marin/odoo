// @ts-check
/** @odoo-module native */

/** @module @web/views/settings/settings_form_view - View descriptor for the settings form view (base_setup) with custom record, model, and compiler */

import { evaluateExpr } from "@web/core/py_js/py";
import { registry } from "@web/core/registry";
import { intersection } from "@web/core/utils/collections/arrays";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import { formView } from "@web/views/form/form_view";

import { SettingsFormCompiler } from "./settings_form_compiler.js";
import { SettingsFormController } from "./settings_form_controller.js";
import { SettingsFormRenderer } from "./settings_form_renderer.js";

/** Record subclass that handles header-field changes with confirmation dialogs. */
class SettingRecord extends formView.Model.Record {
    _update(changes) {
        const changedFields = Object.keys(changes);
        let dirty = true;
        if (
            intersection(changedFields, /** @type {any} */ (this.model)._headerFields)
                .length === changedFields.length
        ) {
            dirty = this.dirty;
            if (this.dirty) {
                // Settings exemption to the base (dirty, _changes) invariant:
                // a header-field edit on an already-dirty record runs the
                // confirm/discard flow and only *then* applies or reverts
                // ``changes``.
                //
                // This MUST stay fire-and-forget (return undefined, do not
                // await the flow here). ``update()`` awaits ``_update()`` inside
                // ``model.mutex.exec`` (see record.js), and the confirm flow
                // itself re-enters that same mutex via
                // ``saveCoordinator.requestDiscard()/requestSave()`` — so
                // returning/awaiting this promise would deadlock the mutex (the
                // "edit header field" Save/Discard paths hang). Releasing the
                // mutex first, then running the flow detached, is required.
                //
                // The only correctness improvement here over the original is the
                // ``.catch``: the detached promise's rejections were previously
                // unhandled; log them instead so a server-side failure in the
                // flow can't surface as an uncaught rejection.
                /** @type {any} */ (
                    async () => {
                        const isDiscard = await /** @type {any} */ (
                            this.model
                        )._onChangeHeaderFields();
                        if (isDiscard) {
                            await /** @type {any} */ (super._update)(changes);
                            this.dirty = false;
                        } else {
                            // Apply and then undo changes to force field components
                            // to re-render and restore previous values (e.g. RadioField).
                            const undoChanges = this._applyChanges(changes);
                            undoChanges();
                        }
                    }
                )().catch((/** @type {any} */ error) => {
                    console.error(error);
                });
                return;
            }
        }
        const prom = /** @type {any} */ (super._update)(changes);
        this.dirty = dirty;
        return prom;
    }
}

/** Model subclass that tracks header fields and forces resId=false on config reload. */
class SettingModel extends formView.Model {
    static withCache = false;

    setup(params) {
        super.setup(/** @type {any} */ (params));
        this._headerFields = params.headerFields;
        this._onChangeHeaderFields = params.onChangeHeaderFields;
    }
    _getNextConfig(currentConfig, params) {
        const nextConfig = super._getNextConfig(currentConfig, params);
        nextConfig.resId = false;
        return nextConfig;
    }
}
SettingModel.Record = SettingRecord;

export const settingsFormView = {
    ...formView,
    display: {},
    Model: SettingModel,
    ControlPanel: ControlPanel,
    Controller: SettingsFormController,
    Compiler: SettingsFormCompiler,
    Renderer: SettingsFormRenderer,
    props: (genericProps, view) => {
        [...genericProps.arch.querySelectorAll("setting[type='header'] field")].forEach(
            (el) => {
                const options = evaluateExpr(el.getAttribute("options") || "{}");
                options.isHeaderField = true;
                el.setAttribute("options", JSON.stringify(options));
            },
        );
        return formView.props(genericProps, view);
    },
};

registry.category("views").add("base_settings", settingsFormView);
