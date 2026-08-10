/** @odoo-module native */
import { _t } from "@web/core/translation";
import {
    BarcodeScanner,
    scanBarcodeOrWarn,
} from "@barcodes/components/barcode_scanner";
import { Component, onWillStart } from "@odoo/owl";
import { isDisplayStandalone } from "@web/core/browser/feature_detection";
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { url } from "@web/core/utils/urls";
import { EventRegistrationSummaryDialog } from "./event_registration_summary_dialog.js";
import { scanBarcode } from "@web/components/barcode";
import { standardActionServiceProps } from "@web/webclient/actions";

export class EventScanView extends Component {
    static template = "event.EventScanView";
    static components = { BarcodeScanner };
    static props = { ...standardActionServiceProps };

    setup() {
        this.actionService = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.orm = useService("orm");

        const { default_event_id, active_model, active_id } = this.props.action.context;
        this.eventId =
            default_event_id || (active_model === "event.event" && active_id);
        this.isMultiEvent = !this.eventId;
        this.isDisplayStandalone = isDisplayStandalone();

        const barcode = useService("barcode");
        useBus(barcode.bus, "barcode_scanned", (ev) =>
            this.onBarcodeScanned(ev.detail.barcode),
        );

        onWillStart(this.onWillStart);
    }

    /**
     * @override
     * Fetch barcode init information. Notably eventId triggers mono- or multi-
     * event mode (Registration Desk in multi event allow to manage attendees
     * from several events and tickets without reloading / changing event in UX.
     */
    async onWillStart() {
        this.data = await rpc("/event/init_barcode_interface", {
            event_id: this.eventId,
        });
        const fileExtension = new Audio().canPlayType("audio/ogg") ? "ogg" : "mp3";
        this.sounds = {
            error: new Audio(url(`/barcodes/static/src/audio/error.${fileExtension}`)),
            notify: new Audio(url(`/mail/static/src/audio/ting.${fileExtension}`)),
        };
        this.sounds.error.load();
        this.sounds.notify.load();
    }

    playSound(type) {
        type = type || "notify";
        this.sounds[type].currentTime = 0;
        this.sounds[type].play();
    }

    /**
     * When scanning a barcode, call Registration.register_attendee() to get
     * formatted registration information, notably its status or event-related
     * information. Open a confirmation / choice Dialog to confirm attendee.
     * @param {Object} barcode
     * @param {function} onNextScanTriggered
     */
    async onBarcodeScanned(barcode, onNextScanTriggered = () => {}) {
        const result = await this.orm.call(
            "event.registration",
            "register_attendee",
            [],
            {
                barcode: barcode,
                event_id: this.eventId,
            },
        );

        if (result.error && result.error === "invalid_ticket") {
            this.playSound("error");
            this.notification.add(_t("Invalid ticket"), {
                type: "danger",
            });
        } else {
            this.registrationId = result.id;
            this.closeLastDialog?.();
            this.closeLastDialog = this.dialog.add(EventRegistrationSummaryDialog, {
                playSound: (type) => this.playSound(type),
                doNextScan: onNextScanTriggered,
                registration: result,
            });
        }
    }

    /**
     * Scan from the dialog rather than through the BarcodeScanner component,
     * which the template here does not mount. The scan itself is the
     * component's, so the two cannot disagree about what a cancelled scan
     * means -- this was a verbatim copy of `openMobileScanner`, and carried
     * its bug of warning the user when they had simply closed the scanner.
     */
    async doNextScan() {
        const barcode = await scanBarcodeOrWarn(
            () => scanBarcode(this.env, this.facingMode),
            this.notification,
        );
        if (barcode) {
            await this.onBarcodeScanned(barcode, this.doNextScan.bind(this));
        }
    }

    onClickSelectAttendee() {
        if (this.isMultiEvent) {
            this.actionService.doAction("event.event_registration_action");
        } else {
            this.actionService.doAction("event.event_registration_action_kanban", {
                additionalContext: {
                    active_id: this.eventId,
                    search_default_unconfirmed: true,
                    search_default_confirmed: true,
                },
            });
        }
    }

    onClickBackToEvents() {
        if (this.isMultiEvent) {
            this.actionService.doAction("event.action_event_view", {
                clearBreadcrumbs: true,
            });
        } else {
            this.actionService.restore();
        }
    }
}

registry.category("actions").add("event.event_barcode_scan_view", EventScanView);
