/** @odoo-module native */
import { Component, useRef } from "@odoo/owl";
import { useListener } from "@web/core/utils/owl_bridge";

import { useScrollShadow } from "../../utils/scroll_shadow_hook.js";

export class CategoryListPopup extends Component {
    static template = "pos_self_order.CategoryListPopup";
    static props = {
        close: Function,
        categories: Object,
        onCategorySelected: Function,
    };

    setup() {
        this.scrollShadow = useScrollShadow(useRef("scrollContainer"));
        useListener(window, "click", this.props.close.bind(this));
    }

    selectCategory(cat) {
        this.props.close();
        this.props.onCategorySelected(cat);
    }
}
