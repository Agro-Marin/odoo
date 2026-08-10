/** @odoo-module native */
import { Component, onMounted, useRef, useState } from "@odoo/owl";
import { BarcodeDialog } from "@web/components/barcode";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { _t } from "@web/core/translation";

export class BarcodeInput extends Component {
    static template = "barcodes.BarcodeInput";
    static props = {
        onSubmit: Function,
        placeholder: { type: String, optional: true },
    };
    static defaultProps = {
        placeholder: _t("Enter a barcode..."),
    };
    setup() {
        this.state = useState({
            barcode: "",
        });
        this.barcodeManual = useRef("manualBarcode");
        // Autofocus processing was blocked because a document already has a focused element.
        onMounted(() => {
            this.barcodeManual.el?.focus();
        });
    }

    submit() {
        // Typed by hand, so it can carry the stray whitespace a scanner would not.
        const barcode = this.state.barcode.trim();
        if (barcode) {
            this.props.onSubmit(barcode);
        }
    }

    /**
     * Called when press Enter after filling barcode input manually.
     *
     * @param {KeyboardEvent} ev
     */
    onKeydown(ev) {
        if (getActiveHotkey(ev) === "enter") {
            this.submit();
        }
    }
}

export class ManualBarcodeScanner extends BarcodeDialog {
    static template = "barcodes.ManualBarcodeScanner";
    static components = {
        ...BarcodeDialog.components,
        BarcodeInput,
    };
    static props = [...BarcodeDialog.props, "placeholder?"];
}
