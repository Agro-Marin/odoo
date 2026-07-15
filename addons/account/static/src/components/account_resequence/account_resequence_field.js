/** @odoo-module native */
import { registry } from "@web/core/registry";
import { Component } from "@odoo/owl";
import { JsonBlobField } from "@account/components/json_blob_field/json_blob_field";

class ChangeLine extends Component {
    static template = "account.ResequenceChangeLine";
    static props = ["changeLine", "ordering"];
}

class ShowResequenceRenderer extends JsonBlobField {
    static template = "account.ResequenceRenderer";
    static components = { ChangeLine };
    get defaultValue() {
        return { changeLines: [], ordering: "date" };
    }
}

registry.category("fields").add("account_resequence_widget", {
    component: ShowResequenceRenderer,
});
