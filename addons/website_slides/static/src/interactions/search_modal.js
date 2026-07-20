/** @odoo-module native */
import { registry } from "@web/core/registry";
import { SearchModal as WebsiteSearchModal } from "@website/interactions/search_modal";

export class SearchModal extends WebsiteSearchModal {
    static selector = "#o_wslides_search_modal";
}

registry
    .category("public.interactions")
    .add("website_slides.search_modal", SearchModal);
