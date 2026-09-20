/** @odoo-module native */
import { useComponent, useEffect } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useService } from "@web/core/utils/hooks";
const log = makeLogger("pos.barcode.hook");
export function useBarcodeReader(callbackMap, exclusive = false) {
    const current = useComponent();
    const barcodeReader = useService("barcode_reader");
    log.lifecycle("useBarcodeReader", () => ({
        component: current.constructor.name,
        types: Object.keys(callbackMap),
        exclusive,
        reader: Boolean(barcodeReader),
    }));
    if (barcodeReader) {
        for (const [key, callback] of Object.entries(callbackMap)) {
            callbackMap[key] = callback.bind(current);
        }
        useEffect(
            () => barcodeReader.register(callbackMap, exclusive),
            () => [],
        );
    }
}
