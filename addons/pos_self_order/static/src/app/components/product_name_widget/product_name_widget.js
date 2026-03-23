/** @odoo-module native */
import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { formatProductName } from "../../utils.js";
import { ProductInfoPopup } from "../product_info_popup/product_info_popup.js";
export class ProductNameWidget extends Component {
    static template = "pos_self_order.ProductNameWidget";
    static props = ["product"];
    setup() {
        this.dialog = useService("dialog");
    }

    displayProductInfo() {
        this.dialog.add(ProductInfoPopup, {
            productTemplate: this.props.product,
        });
    }

    formatProductName(product) {
        return formatProductName(product);
    }
}
