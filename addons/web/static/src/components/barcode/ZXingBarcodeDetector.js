// @ts-check
/** @odoo-module native */

/** @module @web/components/barcode/ZXingBarcodeDetector - BarcodeDetector polyfill built on ZXing for browsers without native support */

/**
 * Builder for BarcodeDetector-like polyfill class using ZXing library.
 *
 * @param {any} ZXing - ZXing library
 * @returns {typeof BarcodeDetector} ZxingBarcodeDetector class
 */
export function buildZXingBarcodeDetector(ZXing) {
    const ZXingFormats = new Map([
        ["aztec", ZXing.BarcodeFormat.AZTEC],
        ["code_39", ZXing.BarcodeFormat.CODE_39],
        ["code_128", ZXing.BarcodeFormat.CODE_128],
        ["data_matrix", ZXing.BarcodeFormat.DATA_MATRIX],
        ["ean_8", ZXing.BarcodeFormat.EAN_8],
        ["ean_13", ZXing.BarcodeFormat.EAN_13],
        ["itf", ZXing.BarcodeFormat.ITF],
        ["pdf417", ZXing.BarcodeFormat.PDF_417],
        ["qr_code", ZXing.BarcodeFormat.QR_CODE],
        ["upc_a", ZXing.BarcodeFormat.UPC_A],
        ["upc_e", ZXing.BarcodeFormat.UPC_E],
    ]);

    const allSupportedFormats = Array.from(ZXingFormats.keys());

    /**
     * Implements the Shape Detection Web API's BarcodeDetector interface.
     */
    class ZXingBarcodeDetector {
        /**
         * @param {object} opts
         * @param {Array} opts.formats list of codes' formats to detect
         */
        constructor(opts = { formats: [] }) {
            const formats = opts.formats.length ? opts.formats : allSupportedFormats;
            const hints = new Map(
                /** @type {any[]} */ ([
                    [
                        ZXing.DecodeHintType.POSSIBLE_FORMATS,
                        formats.map((format) => ZXingFormats.get(format)),
                    ],
                    // Enable Scanning at 90 degrees rotation
                    // https://github.com/zxing-js/library/issues/291
                    [ZXing.DecodeHintType.TRY_HARDER, true],
                ]),
            );
            this.reader = new ZXing.MultiFormatReader();
            this.reader.setHints(hints);
            // Reused across detect() calls (~10/s) to avoid allocating a new
            // canvas per scan tick; resized only when dimensions change.
            this.canvas = document.createElement("canvas");
            this.ctx = this.canvas.getContext("2d");
        }

        /**
         * Detect codes in image.
         *
         * @param {HTMLVideoElement} video source video element
         * @returns {Promise<Array>} array of detected codes
         */
        async detect(video) {
            if (!(video instanceof HTMLVideoElement)) {
                throw new DOMException(
                    "imageDataFrom() requires an HTMLVideoElement",
                    "InvalidArgumentError",
                );
            }
            if (!isVideoElementReady(video)) {
                throw new DOMException(
                    "HTMLVideoElement is not ready",
                    "InvalidStateError",
                );
            }
            const canvas = this.canvas;

            let barcodeArea;
            if (this.cropArea && (this.cropArea.x || this.cropArea.y)) {
                barcodeArea = this.cropArea;
            } else {
                barcodeArea = {
                    x: 0,
                    y: 0,
                    width: video.videoWidth,
                    height: video.videoHeight,
                };
            }
            if (canvas.width !== barcodeArea.width) {
                canvas.width = barcodeArea.width;
            }
            if (canvas.height !== barcodeArea.height) {
                canvas.height = barcodeArea.height;
            }

            const ctx = this.ctx;

            ctx.drawImage(
                video,
                barcodeArea.x,
                barcodeArea.y,
                barcodeArea.width,
                barcodeArea.height,
                0,
                0,
                barcodeArea.width,
                barcodeArea.height,
            );

            const luminanceSource = new ZXing.HTMLCanvasElementLuminanceSource(canvas);
            const binaryBitmap = new ZXing.BinaryBitmap(
                new ZXing.HybridBinarizer(luminanceSource),
            );
            try {
                const result = this.reader.decodeWithState(binaryBitmap);
                const { resultPoints } = result;
                const boundingBox = DOMRectReadOnly.fromRect({
                    x: resultPoints[0].x,
                    y: resultPoints[0].y,
                    height: Math.max(
                        1,
                        Math.abs(resultPoints[1].y - resultPoints[0].y),
                    ),
                    width: Math.max(1, Math.abs(resultPoints[1].x - resultPoints[0].x)),
                });
                const cornerPoints = resultPoints;
                const format = Array.from(ZXingFormats).find(
                    ([k, val]) => val === result.getBarcodeFormat(),
                );
                const rawValue = result.getText();
                return [
                    {
                        boundingBox,
                        cornerPoints,
                        format,
                        rawValue,
                    },
                ];
            } catch (err) {
                if (err.name === "NotFoundException") {
                    return [];
                }
                throw err;
            }
        }

        setCropArea(cropArea) {
            this.cropArea = cropArea;
        }
    }

    /**
     * Supported codes formats
     *
     * @static
     * @returns {Promise<string[]>}
     */
    ZXingBarcodeDetector.getSupportedFormats = async () => allSupportedFormats;

    return ZXingBarcodeDetector;
}

/**
 * Check for HTMLVideoElement readiness.
 *
 * See https://developer.mozilla.org/en-US/docs/Web/API/HTMLMediaElement/readyState
 */
const HAVE_NOTHING = 0;
const HAVE_METADATA = 1;
export function isVideoElementReady(video) {
    return ![HAVE_NOTHING, HAVE_METADATA].includes(video.readyState);
}
