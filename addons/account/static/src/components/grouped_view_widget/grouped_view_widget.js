/** @odoo-module native */
import { JsonBlobField } from "@account/components/json_blob_field/json_blob_field";
import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";

class ListItem extends Component {
    static template = "account.GroupedItemTemplate";
    static props = ["item_vals", "options"];
}

class ListGroup extends Component {
    static template = "account.GroupedItemsTemplate";
    static components = { ListItem };
    static props = ["group_vals", "options"];
}

class ShowGroupedList extends JsonBlobField {
    static template = "account.GroupedListTemplate";
    static components = { ListGroup };
    get defaultValue() {
        return { groups_vals: [], options: { discarded_number: "", columns: [] } };
    }
}

registry.category("fields").add("grouped_view_widget", {
    component: ShowGroupedList,
});
