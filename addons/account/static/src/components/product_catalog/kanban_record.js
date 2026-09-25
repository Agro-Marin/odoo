/** @odoo-module native */
import { productCatalogOrderLines } from "@product/product_catalog/kanban_record";

import { ProductCatalogAccountMoveLine } from "./account_move_line.js";

productCatalogOrderLines.add("account.move", ProductCatalogAccountMoveLine);
