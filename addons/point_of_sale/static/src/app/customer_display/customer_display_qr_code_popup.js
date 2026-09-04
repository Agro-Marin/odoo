/** @odoo-module native */
import { Component, xml } from "@odoo/owl";
import { generateQRCodeDataUrl } from "@point_of_sale/utils";
import { CopyButton } from "@web/components/copy_button";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/ui/dialog";
export class QrCodeCustomerDisplay extends Component {
    static template = "point_of_sale.QrCodeCustomerDisplay";
    static components = { Dialog, CopyButton };
    static props = ["close", "customerDisplayURL"];

    setup() {
        this.ui = useService("ui");
        this.notification = useService("notification");
        this.dialogService = useService("dialog");
    }

    getQrCode() {
        return generateQRCodeDataUrl(this.props.customerDisplayURL);
    }

    /**
     * Where to put the customer display window. When the browser can report the
     * connected screens, a second one gets the whole of its available area;
     * otherwise we keep the small window on this device.
     *
     * https://developer.mozilla.org/en-US/docs/Web/API/Window/getScreenDetails
     */
    async getScreenFeatures() {
        let windowFeatures = "width=800,height=600,left=200,top=200";
        let usedFallback = false;

        if ("getScreenDetails" in window) {
            try {
                const screenDetails = await window.getScreenDetails();
                const secondScreen = screenDetails.screens.find(
                    (screen) => screen !== screenDetails.currentScreen,
                );
                if (secondScreen) {
                    windowFeatures = [
                        `left=${secondScreen.availLeft}`,
                        `top=${secondScreen.availTop}`,
                        `width=${secondScreen.availWidth}`,
                        `height=${secondScreen.availHeight}`,
                    ].join(",");
                }
            } catch {
                // The API is behind the window-management permission, which the
                // cashier can refuse.
                usedFallback = true;
            }
        }
        return { windowFeatures, usedFallback };
    }

    async openOnThisDevice() {
        const { windowFeatures, usedFallback } = await this.getScreenFeatures();
        window.open(this.props.customerDisplayURL, "customerDisplay", windowFeatures);
        this.notification.add(
            usedFallback
                ? _t(
                      "PoS Customer Display opened in a new window. Allow this site to manage windows to use a second screen.",
                  )
                : _t("PoS Customer Display opened in a new window"),
        );
    }

    showQr() {
        const qr = this.getQrCode();
        this.dialogService.add(QrDialog, {
            qrData: qr,
            parentClose: this.props.close,
        });
    }
}

class QrDialog extends Component {
    static props = ["close", "qrData", "parentClose"];
    static components = { Dialog };
    static template = xml`
        <Dialog header="false" footer="false" size="'sm'">
            <div class="d-flex flex-column align-items-center">
                <img id="CustomerDisplayqrCode" t-att-src="props.qrData" alt="Customer QR Code" class="img-fluid mb-3 square w-100"/>
                <button t-on-click="close" class="button btn btn-secondary h1 mb-3 rounded-3">
                    Close
                </button>
            </div>
        </Dialog>
    `;

    close() {
        this.props.close();
        this.props.parentClose();
    }
}
