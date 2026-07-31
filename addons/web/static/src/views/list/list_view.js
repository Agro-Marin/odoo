// @ts-check
/** @odoo-module native */

/** @module @web/views/list/list_view */

import { registry } from "@web/core/registry";
import { RelationalModel } from "@web/model/relational_model/relational_model";

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
        const { ArchParser } = view;
        const { arch, relatedModels, resModel } = genericProps;
        const archInfo = new ArchParser().parse(arch, relatedModels, resModel);
        return {
            ...genericProps,
            readonly: genericProps.readonly || !archInfo.activeActions?.edit,
            Model: view.Model,
            Renderer: view.Renderer,
            buttonTemplate: view.buttonTemplate,
            archInfo,
        };
    },
};

registry.category("views").add("list", listView);
