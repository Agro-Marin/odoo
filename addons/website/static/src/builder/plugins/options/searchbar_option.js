/** @odoo-module native */
import { BaseOptionComponent, useGetItemValue } from "@html_builder/core/utils";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";

const log = makeLogger("website.builder.option.searchbar_option");

export class SearchbarOption extends BaseOptionComponent {
    static template = "website.SearchbarOption";
    static selector = ".s_searchbar_input";
    static applyTo = ".search-query";

    setup() {
        super.setup();
        useLifecycleLog(log);
        this.getItemValue = useGetItemValue();

        this.orderByItems = this.getResource("searchbar_option_order_by_items");
        this.displayItems = this.getResource("searchbar_option_display_items");
    }
}
