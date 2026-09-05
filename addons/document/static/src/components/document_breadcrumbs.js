/** @odoo-module native */
import { DocumentsCogMenu } from "../views/cog_menu/document_cog_menu.js";
import { Breadcrumbs } from "@web/search/breadcrumbs/breadcrumbs";

export class DocumentsBreadcrumbs extends Breadcrumbs {
    static components = {
        ...Breadcrumbs.components,
        DocumentsCogMenu,
    };
    static template = "document.Breadcrumbs";
}
