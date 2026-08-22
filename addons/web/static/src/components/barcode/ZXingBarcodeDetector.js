// @ts-check
/** @odoo-module native */

const MIN_CROP_SIZE = 16;

/**
 * @param {any} ZXing
 * @returns {typeof BarcodeDetector}
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

    class ZXingBarcodeDetector {
        static cropsAtSource = true;

        /**
         * @param {object} opts
         * @param {Array} opts.formats
         */
        constructor(opts = { formats: [] }) {
            const formats = opts.formats.length ? opts.formats : allSupportedFormats;
            const hints = new Map(
                /** @type {any[]} */ ([
                    [
                        ZXing.DecodeHintType.POSSIBLE_FORMATS,
                        formats.map((format) => ZXingFormats.get(format)),
                    ],
                    [ZXing.DecodeHintType.TRY_HARDER, true],
                ]),
            );
            this.reader = new ZXing.MultiFormatReader();
            this.reader.setHints(hints);
            this.canvas = document.createElement("canvas");
            this.ctx = this.canvas.getContext("2d");
        }

        /**
         * @param {HTMLVideoElement} video
         * @returns {Promise<Array>}
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

            const crop = this.cropArea;
            const barcodeArea =
                crop && crop.width >= MIN_CROP_SIZE && crop.height >= MIN_CROP_SIZE
                    ? crop
                    : {
                          x: 0,
                          y: 0,
                          width: video.videoWidth,
                          height: video.videoHeight,
                      };
            if (canvas.width !== barcodeArea.width) {
                canvas.width = barcodeArea.width;
            }
            if (canvas.height !== barcodeArea.height) {
                canvas.height = barcodeArea.height;
            }

            const ctx = /** @type {CanvasRenderingContext2D} */ (this.ctx);

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
                const xs = resultPoints.map((/** @type {any} */ p) => p.x);
                const ys = resultPoints.map((/** @type {any} */ p) => p.y);
                const left = Math.min(...xs);
                const top = Math.min(...ys);
                const boundingBox = DOMRectReadOnly.fromRect({
                    x: left,
                    y: top,
                    width: Math.max(1, Math.max(...xs) - left),
                    height: Math.max(1, Math.max(...ys) - top),
                });
                const cornerPoints = resultPoints;
                const format =
                    Array.from(ZXingFormats).find(
                        ([k, val]) => val === result.getBarcodeFormat(),
                    )?.[0] ?? "";
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
     * @returns {Promise<string[]>}
     */
    ZXingBarcodeDetector.getSupportedFormats = async () => allSupportedFormats;

    return ZXingBarcodeDetector;
}

const HAVE_NOTHING = 0;
const HAVE_METADATA = 1;
export function isVideoElementReady(video) {
    return ![HAVE_NOTHING, HAVE_METADATA].includes(video.readyState);
}
