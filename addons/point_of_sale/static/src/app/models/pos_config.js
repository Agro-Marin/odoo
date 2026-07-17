/** @odoo-module native */
import { getImageDataUrl } from "@point_of_sale/utils";
import { registry } from "@web/core/registry";
import { imageUrl } from "@web/core/utils/urls";

import { logPosMessage } from "../utils/pretty_console_log.js";
import { Base } from "./related_models/index.js";
const CONSOLE_COLOR = "#F5B427";

export class PosConfig extends Base {
    static pythonModel = "pos.config";

    initState() {
        super.initState();
        this.uiState = {};
    }

    // NB: the event-driven price-recompute wiring (handlePricesComputation)
    // was removed: `prices`/`unitPrices` are lazy class getters on
    // PosOrderAccounting — the lazy-getter machinery re-invalidates them
    // automatically whenever any base data they read changes, which is what
    // the create/update listeners here approximated (eagerly, four tax passes
    // per field write).

    get hasCashRounding() {
        return this.cash_rounding && this.only_round_cash_method;
    }
    get hasGlobalRounding() {
        return this.cash_rounding && !this.only_round_cash_method;
    }
    get canInvoice() {
        return Boolean(this.raw.invoice_journal_id);
    }

    get useProxy() {
        return (
            this.is_posbox &&
            (this.iface_electronic_scale ||
                this.iface_print_via_proxy ||
                this.iface_scan_via_proxy ||
                this.iface_customer_facing_display_via_proxy)
        );
    }

    get isShareable() {
        return this.raw.trusted_config_ids.length > 0;
    }

    get printerCategories() {
        const set = new Set();
        for (const relPrinter of this.models["pos.printer"].getAll()) {
            const printer = relPrinter.raw;
            for (const id of printer.product_categories_ids) {
                set.add(id);
            }
        }
        return set;
    }

    get preparationCategories() {
        if (this.printerCategories) {
            return new Set([...this.printerCategories]);
        }
        return new Set();
    }

    get displayBigTrackingNumber() {
        return false;
    }

    get displayTrackingNumber() {
        return this.module_pos_restaurant;
    }

    async cacheReceiptLogo() {
        try {
            this.uiState.receiptLogoDataUrl = await getImageDataUrl(
                this.receiptCompanyLogoUrl,
            );
        } catch (error) {
            logPosMessage(
                "PosConfig",
                "cacheReceiptLogo",
                "Error while caching receipt logo",
                CONSOLE_COLOR,
                [error],
            );
        }
    }

    get receiptLogoUrl() {
        return this.uiState.receiptLogoDataUrl || this.receiptCompanyLogoUrl;
    }

    get receiptCompanyLogoUrl() {
        return imageUrl("res.company", this.company_id.id, "logo", {
            width: 256,
            height: 256,
        });
    }

    get availablePricelists() {
        if (!this.use_pricelist) {
            return [];
        }
        const available_pricelists = new Set(this.available_pricelist_ids);
        if (this.pricelist_id) {
            available_pricelists.add(this.pricelist_id);
        }
        return Array.from(available_pricelists);
    }
}

registry.category("pos_available_models").add(PosConfig.pythonModel, PosConfig);
