/** @odoo-module native */
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list";

const MoveListView = {
    ...listView,
    searchMenuTypes: [],
};

registry.category("views").add('subcontracting_portal_move_list_view', MoveListView);
