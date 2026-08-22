/** @odoo-module native */
import { Sidebar } from "@portal/interactions/sidebar";
import { registry } from "@web/core/registry";

export class SaleSidebar extends Sidebar {
    static selector = ".o_portal_sale_sidebar";

    setup() {
        super.setup();
        this.spyWatched = document.querySelector("body[data-target='.navspy']");
    }

    start() {
        super.start();
        this.generateMenu();
        const searchParams = new URLSearchParams(window.location.search);
        if (searchParams.get("allow_payment") === "yes") {
            this.el.querySelector("#o_sale_portal_paynow")?.click();
        }
    }
}

registry.category("public.interactions").add("sale.sale_sidebar", SaleSidebar);
