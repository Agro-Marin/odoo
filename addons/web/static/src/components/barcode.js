// @ts-check
/** @odoo-module native */

/** @module @web/components/barcode */

/**
 * The barcode module's published interface.
 *
 * Everything under `components/barcode/` that another addon imports today is re-exported here,
 * and nothing else. The names below are the contract; the 2 files behind them
 * are not, and may be renamed, split or moved without touching a
 * consumer OUTSIDE `web`. Inside it they are imported directly and a
 * rename does reach them — the face constrains other addons, which is
 * the only direction `js_face_boundary` enforces.
 *
 * Descriptive rather than aspirational: a face invented ahead of demand is a
 * guess. A consumer needing something not listed adds it here — one visible,
 * reviewable edit instead of a reach into a file.
 *
 * A face is a SIBLING file, not `barcode/index.js`:
 * `ir_qweb_assets._specifier_to_static_url` maps `@web/components/barcode` to
 * `/web/static/src/components/barcode.js` by appending `.js`, with no directory-index step.
 */

export { BarcodeDialog, scanBarcode } from "./barcode/barcode_dialog.js";
export {
    BarcodeVideoScanner,
    isBarcodeScannerSupported,
} from "./barcode/barcode_video_scanner.js";
