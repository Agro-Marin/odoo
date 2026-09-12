/** @odoo-module native */
import { Component, onWillUnmount, useEffect, useState } from "@odoo/owl";
import { AccordionItem } from "@point_of_sale/app/components/accordion_item/accordion_item";
import { useTrackedAsync } from "@point_of_sale/app/hooks/hooks";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useLifecycleLog } from "@web/core/debug/logger_hooks";
import { useService } from "@web/core/utils/hooks";
import { debounce } from "@web/core/utils/timing";
const log = makeLogger("pos.component.product_info_banner");
export class ProductInfoBanner extends Component {
    static template = "point_of_sale.ProductInfoBanner";
    static components = {
        AccordionItem,
    };
    static props = {
        productTemplate: Object,
        product: { type: Object, optional: true },
        info: { type: Object, optional: true },
    };

    setup() {
        useLifecycleLog(log);
        this.pos = usePos();
        this.fetchStock = useTrackedAsync(
            (pt, p) => this.pos.getProductInfo(pt, 1, 0, p),
            {
                keepLast: true,
            },
        );
        this.ui = useService("ui");
        this.state = useState({
            other_warehouses: [],
            available_quantity: 0,
            qty_free: 0,
            uom: "",
        });

        const debouncedFetchStocks = debounce(async (product, productTemplate) => {
            let result;
            log.pipeline("fetchStocks", () => ({
                template: productTemplate?.id,
                product: product?.id,
                fromProps: Boolean(this.props.info),
            }));
            if (!this.props.info) {
                await this.fetchStock.call(productTemplate, product);
                if (this.fetchStock.status === "error") {
                    throw this.fetchStock.result;
                }
                result = this.fetchStock.result;
            } else {
                result = this.props.info;
            }

            if (result) {
                const productInfo = result.productInfo;
                log.logic("fetchStocks: result", () => ({
                    template: productTemplate?.id,
                    warehouses: productInfo.warehouses.length,
                    available: productInfo.warehouses[0]?.available_quantity,
                }));
                this.state.other_warehouses = productInfo.warehouses.slice(1);
                this.state.available_quantity =
                    productInfo.warehouses[0]?.available_quantity;
                this.state.qty_free = productInfo.warehouses[0]?.qty_free;
                this.state.uom = productInfo.warehouses[0]?.uom;
            }
        }, 500);

        useEffect(
            () => {
                if (this.props.productTemplate) {
                    debouncedFetchStocks(
                        this.props.product,
                        this.props.productTemplate,
                    );
                }
            },
            () => [this.props.product],
        );
        onWillUnmount(() => debouncedFetchStocks.cancel());
    }
}
