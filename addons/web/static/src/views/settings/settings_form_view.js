// @ts-check
/** @odoo-module native */

import { evaluateExpr } from "@web/core/py_js/py";
import { registry } from "@web/core/registry";
import { intersection } from "@web/core/utils/collections/arrays";
import { ControlPanel } from "@web/search/control_panel/control_panel";
import { formView } from "@web/views/form/form_view";

import { SettingsFormCompiler } from "./settings_form_compiler.js";
import { SettingsFormController } from "./settings_form_controller.js";
import { SettingsFormRenderer } from "./settings_form_renderer.js";

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
                /** @type {any} */ (
                    async () => {
                        const isDiscard = await /** @type {any} */ (
                            this.model
                        )._onChangeHeaderFields();
                        if (isDiscard) {
                            await /** @type {any} */ (super._update)(changes);
                            this.dirty = false;
                        } else {
                            const undoChanges = this._applyChanges(
                                changes,
                                {},
                                {
                                    undoable: true,
                                },
                            );
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

class SettingModel extends formView.Model {
    static withCache = false;

    setup(params, services) {
        super.setup(/** @type {any} */ (params), services);
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

const settingsFormView = {
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
