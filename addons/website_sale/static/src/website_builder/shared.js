/** @odoo-module native */
import { _t } from "@web/core/translation";

export const products_sort_mapping = [
    {
        query: "website_sequence asc",
        label: _t("Featured"),
    },
    {
        query: "publish_date desc",
        label: _t("Newest Arrivals"),
    },
    {
        query: "name asc",
        label: _t("Name (A-Z)"),
    },
    {
        query: "list_price asc",
        label: _t("Price - Low to High"),
    },
    {
        query: "list_price desc",
        label: _t("Price - High to Low"),
    },
];
