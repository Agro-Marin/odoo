/** @odoo-module native */
import { _t } from "@web/core/l10n/translation";

import { SaleActionHelper } from "../js/sale_action_helper/sale_action_helper.js";

/**
 * Class factories shared by the sale RFQ-upload and onboarding kanban/list views.
 *
 * The kanban and list variants differ only in the account base class they extend, so
 * the (identical) behaviour is defined once here and applied to each base. Crucially,
 * this keeps the translated drop-zone copy in a single place instead of duplicating
 * the `msgid` across four source files.
 */

/**
 * Extend a file-upload controller to hide the "Upload" button (the RFQ import flow
 * uses the drop zone instead).
 *
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
 * Extend a file-upload renderer with the RFQ-import drop-zone title and description.
 *
 * @param {typeof import("@web/views/kanban/kanban_renderer").KanbanRenderer} Renderer
 */
export const saleFileUploadRenderer = (Renderer) =>
    class extends Renderer {
        setup() {
            super.setup();
            this.dropZoneTitle = _t("Import a request for quotation from a customer");
            this.dropZoneDescription = _t(`
            If your customer runs on Odoo 18 or higher, customer data and sales order lines
            will be automatically created. Any other pdf containing an attached
            UBL-RequestForQuotation file will work as well.
        `);
        }
    };

/**
 * Extend a renderer to display the onboarding action helper (the "no content" video
 * preview) and use the given onboarding template.
 *
 * @param {typeof import("@web/views/kanban/kanban_renderer").KanbanRenderer} Renderer
 * @param {String} template The onboarding renderer template name.
 */
export const saleOnboardingRenderer = (Renderer, template) =>
    class extends Renderer {
        static template = template;
        static components = { ...Renderer.components, SaleActionHelper };
    };
