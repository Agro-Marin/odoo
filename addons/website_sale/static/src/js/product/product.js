/** @odoo-module native */
import { Product } from "@sale/js/product/product";
import { formatCurrency } from "@web/core/currency";
import { patch } from "@web/core/utils/patch";
import { useProductConfiguratorContext } from "@sale/js/product_configurator_dialog/product_configurator_context";

patch(Product, {
    props: {
        ...Product.props,
        strikethrough_price: { type: Number, optional: true },
        can_be_sold: { type: Boolean, optional: true },
        category_name: { type: String, optional: true },
        currency_name: { type: String, optional: true },
    },
});

patch(Product.prototype, {
    setup() {
        super.setup(...arguments);
        this.configuratorContext = useProductConfiguratorContext();
    },

    /**
     * @return {String}
     */
    get formattedStrikethroughPrice() {
        return formatCurrency(
            this.props.strikethrough_price,
            this.configuratorContext.currency.id,
        );
    },
});
