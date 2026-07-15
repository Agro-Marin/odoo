/** @odoo-module native */

/**
 * Shared helpers for the BoM Overview and MO Overview component trees.
 * These trees mirror each other, so the small bits of logic they have in
 * common live here to avoid drift between the two.
 */

/** Bootstrap text-color class for a decorator name (e.g. "danger" -> "text-danger"). */
export function getColorClass(decorator) {
    return decorator ? `text-${decorator}` : "";
}

/** Name of the forecast report action for a given product model. */
export function getForecastAction(model) {
    switch (model) {
        case "product.product":
            return "action_product_forecast_report";
        case "product.template":
            return "action_product_tmpl_forecast_report";
    }
}
