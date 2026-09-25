/** @odoo-module native */
import { onWillDestroy } from "@odoo/owl";
import {
    provideProductCatalogContext,
    useProductCatalogContext,
} from "@product/product_catalog/product_catalog_context";
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { useDebounced } from "@web/core/utils/timing";
import { useSearchModel } from "@web/search/search_model";
import { KanbanRecord } from "@web/views/kanban";

import { ProductCatalogOrderLine } from "./order_line/order_line.js";

/**
 * Order-line components by order model, e.g. `"purchase.order"`.
 *
 * A module that ships its own line component registers it here instead of
 * patching `orderLineComponent` with one more `res_model` comparison: the
 * lookup stays O(1), the set of extensions is enumerable from this module, and
 * two modules cannot silently race to answer for the same model.
 */
export const productCatalogOrderLines = registry.category(
    "product_catalog_order_lines",
);

export const productCatalogKanbanRecordProps = [...KanbanRecord.props];

export class ProductCatalogKanbanRecord extends KanbanRecord {
    static props = productCatalogKanbanRecordProps;
    static template = "ProductCatalogKanbanRecord";
    static components = {
        ...KanbanRecord.components,
        ProductCatalogOrderLine,
    };

    setup() {
        super.setup();
        this.searchModel = useSearchModel();
        this.debouncedUpdateQuantity = useDebounced(
            this._updateQuantity.bind(this),
            500,
            {
                execBeforeUnmount: true,
            },
        );
        this._pendingUpdate = Promise.resolve();

        // Leaving the catalog has to outlast the debounce above.
        // `execBeforeUnmount` does fire the pending write, but nothing awaits
        // it, so a card touched less than 500ms before leaving had its write
        // still in flight while the order form was already reloading -- and the
        // line the user just added was simply absent. Register a flush the
        // controller awaits in `beforeLeave`, which every exit goes through.
        const parentCatalog = useProductCatalogContext();
        parentCatalog.productCatalogPendingUpdates?.add(this);
        onWillDestroy(() => parentCatalog.productCatalogPendingUpdates?.delete(this));

        provideProductCatalogContext({
            currencyId: this.props.record.context.product_catalog_currency_id,
            orderId: this.props.record.context.order_id,
            orderResModel: this.props.record.context.product_catalog_order_model,
            digits: this.props.record.context.product_catalog_digits,
            displayUoM: this.props.record.context.display_uom,
            precision: this.props.record.context.precision,
            productId: this.props.record.resId,
            addProduct: this.addProduct.bind(this),
            removeProduct: this.removeProduct.bind(this),
            increaseQuantity: this.increaseQuantity.bind(this),
            setQuantity: this.setQuantity.bind(this),
            decreaseQuantity: this.decreaseQuantity.bind(this),
            childField: this.props.record.context.child_field,
        });
        this.catalogContext = useProductCatalogContext();
    }

    get orderLineComponent() {
        return productCatalogOrderLines.get(
            this.catalogContext.orderResModel,
            ProductCatalogOrderLine,
        );
    }

    get productCatalogData() {
        return this.props.record.productCatalogData;
    }

    onGlobalClick(ev) {
        // avoid a concurrent update when clicking on the buttons (that are inside the record)
        if (ev.target.closest(".o_product_catalog_cancel_global_click")) {
            return;
        }
        if (this.productCatalogData.quantity === 0) {
            this.addProduct();
        } else {
            this.increaseQuantity();
        }
    }

    //--------------------------------------------------------------------------
    // Data Exchanges
    //--------------------------------------------------------------------------

    async _updateQuantity() {
        const price = await this._updateQuantityAndGetPrice();
        this.productCatalogData.price = parseFloat(price);
    }

    /**
     * Run any debounced quantity write now and resolve once it has landed.
     *
     * @returns {Promise<any>}
     */
    flushPendingUpdate() {
        // `cancel(true)` runs the pending call synchronously, which reassigns
        // `_pendingUpdate` to the resulting request before this returns.
        this.debouncedUpdateQuantity.cancel(true);
        return this._pendingUpdate;
    }

    _updateQuantityAndGetPrice() {
        // Chain RPC calls to ensure that each request is completed before starting the next one.
        // This prevents race conditions and ensures the server processes updates sequentially.
        // The `.catch` resets the chain after a failed call so a single rejected
        // request doesn't permanently block every subsequent update on this card.
        this._pendingUpdate = this._pendingUpdate
            .catch(() => {})
            .then(() =>
                rpc(
                    "/product/catalog/update_order_line_info",
                    this._getUpdateQuantityAndGetPriceParams(),
                ),
            );
        return this._pendingUpdate;
    }

    get sectionIdOfPendingUpdate() {
        return this._sectionIdOfPendingUpdate === undefined
            ? this.searchModel.selectedSection.sectionId
            : this._sectionIdOfPendingUpdate;
    }

    _getUpdateQuantityAndGetPriceParams() {
        return {
            order_id: this.catalogContext.orderId,
            product_id: this.catalogContext.productId,
            quantity: this.productCatalogData.quantity,
            res_model: this.catalogContext.orderResModel,
            child_field: this.catalogContext.childField,
            section_id: this.sectionIdOfPendingUpdate,
        };
    }

    notifyLineCountChange(lineCountChange) {
        this.searchModel.trigger("section-line-count-change", {
            sectionId: this.sectionIdOfPendingUpdate,
            lineCountChange: lineCountChange,
        });
    }

    //--------------------------------------------------------------------------
    // Handlers
    //--------------------------------------------------------------------------

    updateQuantity(quantity) {
        this._sectionIdOfPendingUpdate = this.searchModel.selectedSection.sectionId;
        if (this.productCatalogData.readOnly) {
            return;
        }
        const lineCountChange = (quantity > 0) - (this.productCatalogData.quantity > 0);
        if (lineCountChange !== 0) {
            this.notifyLineCountChange(lineCountChange);
        }
        // A catalog line is never negative: removing more than is on the order
        // takes the product off it, it does not owe any back.
        this.productCatalogData.quantity = Math.max(0, quantity || 0);
        this.debouncedUpdateQuantity();
    }

    /**
     * Add the product to the order
     */
    addProduct(qty = 1) {
        if (
            this.productCatalogData.quantity === 0 &&
            qty < this.productCatalogData.min_qty
        ) {
            qty = this.productCatalogData.min_qty;
        }
        this.updateQuantity(qty);
    }

    /**
     * Remove the product to the order
     */
    removeProduct() {
        this.updateQuantity(0);
    }

    /**
     * Increase the quantity of the product on the order line.
     */
    increaseQuantity(qty = 1) {
        this.updateQuantity(this.productCatalogData.quantity + qty);
    }

    /**
     * Set the quantity of the product on the order line.
     *
     * @param {Event} event
     */
    setQuantity(event) {
        this.updateQuantity(parseFloat(event.target.value));
    }

    /**
     * Decrease the quantity of the product on the order line.
     */
    decreaseQuantity() {
        this.updateQuantity(this.productCatalogData.quantity - 1);
    }
}
