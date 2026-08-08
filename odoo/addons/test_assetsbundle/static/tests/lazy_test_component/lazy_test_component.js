import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";

export class LazyTestComponent extends Component {
    static template = "test_assetsbundle.LazyTestComponent";
    static props = ["*"];
    setup() {
        this.props.onCreated();
    }
}

registry.category("lazy_components").add("LazyTestComponent", LazyTestComponent);
