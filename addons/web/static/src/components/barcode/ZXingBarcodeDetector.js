// @ts-check
/** @odoo-module native */

const MIN_CROP_SIZE = 16;
const HAVE_METADATA = 1;

/** Our format names, in the order a caller gets them from getSupportedFormats. */
const FORMAT_NAMES = [
    "aztec",
    "code_39",
    "code_128",
    "data_matrix",
    "ean_8",
    "ean_13",
    "itf",
    "pdf417",
    "qr_code",
    "upc_a",
    "upc_e",
];

/**
 * ZXing spells the same formats as enum members; map both ways once, because the
 * reverse direction is read on every successful decode.
 * @param {any} ZXing
 * @returns {{ toZXing: Map<string, any>, toName: Map<any, string> }}
 */
function buildFormatTables(ZXing) {
    const toZXing = new Map(
        FORMAT_NAMES.map((name) => [name, ZXing.BarcodeFormat[name.toUpperCase()]]),
    );
    return {
        toZXing,
        toName: new Map(Array.from(toZXing, ([name, value]) => [value, name])),
    };
}

/**
 * Called once per frame while the camera is open, so it does not allocate.
 * @param {HTMLVideoElement | null} video
 * @returns {boolean}
 */
export function isVideoElementReady(video) {
    return video ? video.readyState > HAVE_METADATA : false;
}

/**
 * A `BarcodeDetector` built on ZXing, for the browsers that ship no native one.
 *
 * `cropsAtSource` is the flag the scanner reads to decide whether to hand this a
 * crop rectangle (which it draws from) or to crop the frame itself first.
 *
 * @param {any} ZXing
 * @returns {typeof BarcodeDetector}
 */
export class ZXingBarcodeDetector {
    static cropsAtSource = true;

    /** @returns {Promise<string[]>} */
    static async getSupportedFormats() {
        return [...FORMAT_NAMES];
    }

    /**
     * @param {any} ZXing
     * @param {{ toZXing: Map<string, any>, toName: Map<any, string> }} formats
     * @param {object} opts
     * @param {Array} opts.formats
     */
    constructor(ZXing, formats, opts = { formats: [] }) {
        const wanted = opts.formats.length ? opts.formats : FORMAT_NAMES;
        this.ZXing = ZXing;
        this.formats = formats;
        this.reader = new ZXing.MultiFormatReader();
        this.reader.setHints(
            new Map(
                /** @type {any[]} */ ([
                    [
                        ZXing.DecodeHintType.POSSIBLE_FORMATS,
                        wanted.map((format) => formats.toZXing.get(format)),
                    ],
                    [ZXing.DecodeHintType.TRY_HARDER, true],
                ]),
            ),
        );
        this.canvas = document.createElement("canvas");
        this.ctx = this.canvas.getContext("2d");
        /** @type {{x: number, y: number, width: number, height: number} | undefined} */
        this.cropArea = undefined;
    }

    /**
     * @param {{x: number, y: number, width: number, height: number}} cropArea
     */
    setCropArea(cropArea) {
        this.cropArea = cropArea;
    }

    /**
     * The rectangle of the frame to decode: the crop the scanner asked for,
     * unless it is too small to hold a barcode, in which case the whole frame.
     * @param {HTMLVideoElement} video
     * @returns {{x: number, y: number, width: number, height: number}}
     */
    barcodeAreaOf(video) {
        const crop = this.cropArea;
        if (crop && crop.width >= MIN_CROP_SIZE && crop.height >= MIN_CROP_SIZE) {
            return crop;
        }
        return {
            x: 0,
            y: 0,
            width: video.videoWidth,
            height: video.videoHeight,
        };
    }

    /**
     * @param {HTMLVideoElement} video
     * @returns {any} a ZXing BinaryBitmap of the area to decode
     */
    captureBitmap(video) {
        const { x, y, width, height } = this.barcodeAreaOf(video);
        const canvas = this.canvas;
        if (canvas.width !== width) {
            canvas.width = width;
        }
        if (canvas.height !== height) {
            canvas.height = height;
        }
        /** @type {CanvasRenderingContext2D} */ (this.ctx).drawImage(
            video,
            x,
            y,
            width,
            height,
            0,
            0,
            width,
            height,
        );
        const { ZXing } = this;
        return new ZXing.BinaryBitmap(
            new ZXing.HybridBinarizer(
                new ZXing.HTMLCanvasElementLuminanceSource(canvas),
            ),
        );
    }

    /**
     * @param {any} result
     * @returns {Record<string, any>} in the shape the native BarcodeDetector uses
     */
    static toDetectedBarcode(result, toName) {
        const { resultPoints } = result;
        const xs = resultPoints.map((/** @type {any} */ p) => p.x);
        const ys = resultPoints.map((/** @type {any} */ p) => p.y);
        const left = Math.min(...xs);
        const top = Math.min(...ys);
        return {
            boundingBox: DOMRectReadOnly.fromRect({
                x: left,
                y: top,
                width: Math.max(1, Math.max(...xs) - left),
                height: Math.max(1, Math.max(...ys) - top),
            }),
            cornerPoints: resultPoints,
            format: toName.get(result.getBarcodeFormat()) ?? "",
            rawValue: result.getText(),
        };
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
        const bitmap = this.captureBitmap(video);
        try {
            const result = this.reader.decodeWithState(bitmap);
            return [
                ZXingBarcodeDetector.toDetectedBarcode(result, this.formats.toName),
            ];
        } catch (err) {
            // The overwhelmingly common outcome: this frame held no barcode.
            if (err.name === "NotFoundException") {
                return [];
            }
            throw err;
        }
    }
}

/**
 * Binds a ZXing build to the detector, so callers construct it the way they
 * construct the native `BarcodeDetector`: `new Detector({ formats })`.
 *
 * @param {any} ZXing
 * @returns {typeof BarcodeDetector}
 */
export function buildZXingBarcodeDetector(ZXing) {
    const formats = buildFormatTables(ZXing);
    return /** @type {any} */ (
        class BoundZXingBarcodeDetector extends ZXingBarcodeDetector {
            /** @param {object} [opts] */
            constructor(opts) {
                super(ZXing, formats, opts);
            }
        }
    );
}
