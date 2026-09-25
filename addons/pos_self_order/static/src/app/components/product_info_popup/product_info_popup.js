/** @odoo-module native */
import { Component, useRef, useState } from "@odoo/owl";
import { useListener } from "@web/core/utils/owl_bridge";

import { useScrollShadow } from "../../utils/scroll_shadow_hook.js";
export class ProductInfoPopup extends Component {
    static template = "pos_self_order.ProductInfoPopup";
    static props = {
        productTemplate: Object,
        close: Function,
    };

    setup() {
        this.scrollShadow = useScrollShadow(useRef("scrollContainer"));
        useListener(window, "click", this.props.close.bind(this));
        this.state = useState({
            qty: 1,
        });
    }
}
