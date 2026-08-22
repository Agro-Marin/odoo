/** @odoo-module native */
import { Component } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { logPosMessage } from "@point_of_sale/app/utils/pretty_console_log";
import { _t } from "@web/core/translation";
import { AlertDialog, Dialog } from "@web/ui/dialog";
export class ProductInfoPopup extends Component {
    static template = "point_of_sale.ProductInfoPopup";
    static components = { Dialog };
    static props = ["info", "productTemplate", "close"];

    setup() {
        this.pos = usePos();
    }
    searchProduct(productName) {
        this.pos.setSelectedCategory(0);
        this.pos.searchProductWord = productName;
        this.props.close();
    }
    _hasMarginsCostsAccessRights() {
        if (!this.pos.config.is_margins_costs_accessible_to_every_user) {
            return false;
        }
        return ["manager", "cashier"].includes(this.pos.getCashier()._role);
    }
    editProduct() {
        this.pos.editProduct(this.props.productTemplate);
        this.props.close();
    }
    get allowProductEdition() {
        return true;
    }
    async toggleFavorite() {
        const template = this.props.productTemplate;
        const next = !template.is_favorite;
        try {
            const applied = await this.pos.data.call(
                "product.template",
                "set_pos_favorite",
                [[template.id], next],
            );
            template.is_favorite = applied;
        } catch (error) {
            this.pos.dialog.add(AlertDialog, {
                title: _t("Favourite not saved"),
                body: _t("This product could not be marked as a favourite."),
            });
            logPosMessage(
                "ProductInfoPopup",
                "toggleFavorite",
                `Could not set is_favorite on product.template ${template.id}`,
                undefined,
                [error],
            );
        }
    }
    get vatLabel() {
        return _t("VAT:");
    }
    get totalVatLabel() {
        return _t("Total VAT:");
    }
}
