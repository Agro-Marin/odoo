// @ts-check
/** @odoo-module native */

/** @module @web/views/form/form_view - View registry descriptor for the standard form view */

import { registry } from "@web/core/registry";
import { RelationalModel } from "@web/model/relational_model/relational_model";

import { FormArchParser } from "./form_arch_parser.js";
import { FormCompiler } from "./form_compiler.js";
import { FormController } from "./form_controller.js";
import { FormRenderer } from "./form_renderer.js";

/** View registry descriptor for the standard form view. */
export const formView = {
    type: "form",
    searchMenuTypes: [],
    Controller: FormController,
    Renderer: FormRenderer,
    ArchParser: FormArchParser,
    Model: RelationalModel,
    Compiler: FormCompiler,
    buttonTemplate: "web.FormView.Buttons",

    props: (genericProps, view) => {
        const { ArchParser } = view;
        const { arch, relatedModels, resModel } = genericProps;
        const archInfo = new ArchParser().parse(arch, relatedModels, resModel);

        return {
            ...genericProps,
            readonly:
                genericProps.readonly ||
                (archInfo.activeActions?.edit === false &&
                    genericProps.resId !== false),
            Model: view.Model,
            Renderer: view.Renderer,
            buttonTemplate: genericProps.buttonTemplate || view.buttonTemplate,
            Compiler: view.Compiler,
            archInfo,
        };
    },
};

registry.category("views").add("form", /** @type {any} */ (formView));
