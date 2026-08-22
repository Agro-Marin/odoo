/** @odoo-module native */
class PurchaseAdditionalTourSteps {
    getPurchaseStockSteps() {
        return [
            {
                // Useless final step to trigger congratulation message
                isActive: ["auto"],
                trigger: ".o_purchase_order",
                run: "click",
            },
        ];
    }
}

export default PurchaseAdditionalTourSteps;
