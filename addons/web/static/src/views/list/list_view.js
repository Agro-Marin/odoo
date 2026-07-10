// @ts-check
/** @odoo-module native */

/** @module @web/views/list/list_view - List (tree) view descriptor registered in the view registry */

import { registry } from "@web/core/registry";
import { RelationalModel } from "@web/model/relational_model/relational_model";

import { ListArchParser } from "./list_arch_parser.js";
import { ListController } from "./list_controller.js";
import { ListRenderer } from "./list_renderer.js";

/**
 * View descriptor for the list (tree) view type, registered under "list".
 *
 * Type annotation intentionally omitted: ``ViewRegistryEntry`` types
 * ``Controller``/``Renderer`` as ``ComponentConstructor``, which OWL class
 * types don't currently satisfy (see ``JSDOC_TYPE_TIGHTENING.md``). Sibling
 * view files follow the same untyped-export convention.
 */
export const listView = {
    type: "list",

    Controller: ListController,
    Renderer: ListRenderer,
    ArchParser: ListArchParser,
    Model: RelationalModel,

    buttonTemplate: "web.ListView.Buttons",

    canOrderByCount: true,

    /**
     * Build component props from generic view props and the view descriptor.
     *
     * Parses the arch XML via {@link ListArchParser} and merges the result
     * into the props passed to {@link ListController}.
     *
     * @param {Record<string, any>} genericProps - standard view props (arch, resModel, fields, etc.)
     * @param {Record<string, any>} view - the view descriptor (typed loosely to avoid the
     *     circular ``typeof listView`` self-reference; the only fields read here are
     *     ``ArchParser``, ``Model``, ``Renderer``, ``buttonTemplate``).
     * @returns {Record<string, any>} props for ListController
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
