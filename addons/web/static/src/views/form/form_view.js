// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";
import { RelationalModel } from "@web/model/relational_model/relational_model";
import { defaultViewProps } from "@web/views/view_utils";

import { FormArchParser } from "./form_arch_parser.js";
import { FormCompiler } from "./form_compiler.js";
import { FormController } from "./form_controller.js";
import { FormRenderer } from "./form_renderer.js";

export const formView = {
    type: "form",
    /** @type {string[]} */
    searchMenuTypes: [],
    Controller: FormController,
    Renderer: FormRenderer,
    ArchParser: FormArchParser,
    Model: RelationalModel,
    Compiler: FormCompiler,
    buttonTemplate: "web.FormView.Buttons",

    /**
     * @param {any} genericProps
     * @param {any} view
     */
    props: (genericProps, view) => {
        const props = defaultViewProps(genericProps, view);
        props.readonly =
            genericProps.readonly ||
            (props.archInfo.activeActions?.edit === false &&
                genericProps.resId !== false);
        props.buttonTemplate = genericProps.buttonTemplate || view.buttonTemplate;
        return props;
    },
};

registry.category("views").add("form", /** @type {any} */ (formView));
