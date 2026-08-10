/** @odoo-module native */
import { ListController } from "@web/views/list";

export class TodoListController extends ListController {
    setup() {
        super.setup();
        // The To-Do list arch carries no `active` field, so computeArchiveEnabled
        // would hide Archive/Unarchive. The records are archivable server-side,
        // so force it on here rather than adding a column nobody wants. This has
        // to happen before actionMenuItems is read, which is why it is in setup.
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
