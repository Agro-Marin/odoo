/** @odoo-module native */
import { DocumentsCogMenu } from "../views/cog_menu/document_cog_menu.js";
import { Breadcrumbs } from "@web/search/breadcrumbs/breadcrumbs";
import { useService } from "@web/core/utils/hooks";

export class DocumentsBreadcrumbs extends Breadcrumbs {
    static components = {
        ...Breadcrumbs.components,
        DocumentsCogMenu,
    };
    static template = "document.Breadcrumbs";

    setup() {
        super.setup();
        this.ui = useService("ui");
    }
}
