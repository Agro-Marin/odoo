/** @odoo-module native */
import { ListController } from "@web/views/list";

export class TodoListController extends ListController {
    setup() {
        super.setup();
        this.archiveEnabled = true;
    }

    get actionMenuItems() {
        const actionToKeep = ["export", "archive", "unarchive", "duplicate", "delete"];
        const menuItems = super.actionMenuItems;
        const filteredActions =
            menuItems.action?.filter((action) => actionToKeep.includes(action.key)) ||
            [];
        menuItems.action = filteredActions;
        menuItems.print = [];
        return menuItems;
    }
}
