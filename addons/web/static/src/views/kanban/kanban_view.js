// @ts-check
/** @odoo-module native */

/** @module @web/views/kanban/kanban_view */

import { registry } from "@web/core/registry";
import { RelationalModel } from "@web/model/relational_model/relational_model";
import { defaultViewProps } from "@web/views/view_utils";

import { KanbanArchParser } from "./kanban_arch_parser.js";
import { KanbanCompiler } from "./kanban_compiler.js";
import { KanbanController } from "./kanban_controller.js";
import { KanbanRenderer } from "./kanban_renderer.js";

/**
 * @type {{
 *   type: string,
 *   ArchParser: typeof KanbanArchParser,
 *   Controller: typeof KanbanController,
 *   Model: typeof RelationalModel,
 *   Renderer: typeof KanbanRenderer,
 *   Compiler: typeof KanbanCompiler,
 *   buttonTemplate: string,
 *   props: (genericProps: Object, view: Object) => Object,
 * }}
 */
export const kanbanView = {
    type: "kanban",

    ArchParser: KanbanArchParser,
    Controller: KanbanController,
    Model: RelationalModel,
    Renderer: KanbanRenderer,
    Compiler: KanbanCompiler,

    buttonTemplate: "web.KanbanView.Buttons",

    props: (genericProps, view) => {
        const props = defaultViewProps(genericProps, view);
        props.readonly = genericProps.readonly || !props.archInfo.activeActions?.edit;
        return props;
    },
};

registry.category("views").add("kanban", kanbanView);
