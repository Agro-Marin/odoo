/** @odoo-module native */
import { useEffect } from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";
import { useService } from "@web/core/utils/hooks";
import { useComponentName } from "@web/core/utils/owl_bridge";
const log = makeLogger("pos.barcode.hook");
export function useBarcodeReader(callbackMap, exclusive = false) {
    const componentName = useComponentName();
    const barcodeReader = useService("barcode_reader");
    log.lifecycle("useBarcodeReader", () => ({
        component: componentName,
        types: Object.keys(callbackMap),
        exclusive,
        reader: Boolean(barcodeReader),
    }));
    if (barcodeReader) {
        useEffect(
            () => barcodeReader.register(callbackMap, exclusive),
            () => [],
        );
    }
}
