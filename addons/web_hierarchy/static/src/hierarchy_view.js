/** @odoo-module native */
import { registry } from "@web/core/registry";
import { defaultViewProps } from "@web/views/view_utils";
import { HierarchyArchParser } from "./hierarchy_arch_parser.js";
import { HierarchyController } from "./hierarchy_controller.js";
import { HierarchyModel } from "./hierarchy_model.js";
import { HierarchyRenderer } from "./hierarchy_renderer.js";

export const hierarchyView = {
    type: "hierarchy",
    ArchParser: HierarchyArchParser,
    Controller: HierarchyController,
    Model: HierarchyModel,
    Renderer: HierarchyRenderer,
    buttonTemplate: "web_hierarchy.HierarchyButtons",
    searchMenuTypes: ["filter"],
    props: defaultViewProps,
};

registry.category("views").add("hierarchy", hierarchyView);
