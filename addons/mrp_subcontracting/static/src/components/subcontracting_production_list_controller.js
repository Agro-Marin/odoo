/** @odoo-module native */
import { registry } from "@web/core/registry";
import { ListController, listView } from "@web/views/list";

class SubcontractingProductionListController extends ListController {
    get actionMenuItems() {
        let items = super.actionMenuItems;
        items.action = []
        return items;
    }
}

registry.category("views").add("subcontracting_production_list", {
    ...listView,
    Controller: SubcontractingProductionListController,
});
