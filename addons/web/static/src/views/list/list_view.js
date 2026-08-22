// @ts-check
/** @odoo-module native */

import { registry } from "@web/core/registry";
import { RelationalModel } from "@web/model/relational_model/relational_model";
import { multiRecordViewProps } from "@web/views/view_utils";

import { ListArchParser } from "./list_arch_parser.js";
import { ListController } from "./list_controller.js";
import { ListRenderer } from "./list_renderer.js";

export const listView = {
    type: "list",

    Controller: ListController,
    Renderer: ListRenderer,
    ArchParser: ListArchParser,
    Model: RelationalModel,

    buttonTemplate: "web.ListView.Buttons",

    canOrderByCount: true,

    props: multiRecordViewProps,
};

registry.category("views").add("list", listView);
