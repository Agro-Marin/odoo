// @ts-check
/** @odoo-module native */

/** @module @web/views/list/list_view */

import { registry } from "@web/core/registry";
import { RelationalModel } from "@web/model/relational_model/relational_model";
import { defaultViewProps } from "@web/views/view_utils";

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

    /**
     * @param {Record<string, any>} genericProps
     * @param {Record<string, any>} view
     * @returns {Record<string, any>}
     */
    props: (genericProps, view) => {
        const props = defaultViewProps(genericProps, view);
        props.readonly = genericProps.readonly || !props.archInfo.activeActions?.edit;
        return props;
    },
};

registry.category("views").add("list", listView);
