/** @odoo-module native */
import { _t } from "@web/core/translation";

import { SaleActionHelper } from "../js/sale_action_helper/sale_action_helper.js";

/**
 * @param {typeof import("@web/views/kanban/kanban_controller").KanbanController} Controller
 */
export const saleFileUploadController = (Controller) =>
    class extends Controller {
        setup() {
            super.setup();
            this.hideUploadButton = true;
        }
    };

/**
 * @param {typeof import("@web/views/kanban/kanban_renderer").KanbanRenderer} Renderer
 */
export const saleFileUploadRenderer = (Renderer) =>
    class extends Renderer {
        setup() {
            super.setup();
            this.dropZoneTitle = _t("Import a request for quotation from a customer");
            this.dropZoneDescription = _t(
                "If your customer runs on Odoo 18 or higher, customer data and sales" +
                    " order lines will be automatically created. Any other pdf" +
                    " containing an attached UBL-RequestForQuotation file will work" +
                    " as well.",
            );
        }
    };

/**
 * @param {typeof import("@web/views/kanban/kanban_renderer").KanbanRenderer} Renderer
 * @param {String} template
 */
export const saleOnboardingRenderer = (Renderer, template) =>
    class extends Renderer {
        static template = template;
        static components = { ...Renderer.components, SaleActionHelper };
    };
