/** @odoo-module native */

export function getColorClass(decorator) {
    return decorator ? `text-${decorator}` : "";
}

export function getForecastAction(model) {
    switch (model) {
        case "product.product":
            return "action_product_forecast_report";
        case "product.template":
            return "action_product_tmpl_forecast_report";
    }
}
