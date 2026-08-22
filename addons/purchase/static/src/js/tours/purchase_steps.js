/** @odoo-module native */
class PurchaseAdditionalTourSteps {
    getPurchaseStockSteps() {
        return [
            {
                isActive: ["auto"],
                trigger: ".o_purchase_order",
                run: "click",
            },
        ];
    }
}

export default PurchaseAdditionalTourSteps;
