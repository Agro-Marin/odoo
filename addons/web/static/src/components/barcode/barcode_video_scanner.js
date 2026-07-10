// @ts-check
/** @odoo-module native */

/** @module @web/components/barcode/barcode_video_scanner - Camera-based barcode scanner using BarcodeDetector API with ZXing fallback */

/* global BarcodeDetector -- polyfilled at runtime */
/* eslint no-redeclare: ["error", { builtinGlobals: false }] */

import {
    Component,
    onMounted,
    onWillStart,
    onWillUnmount,
    status,
    useRef,
    useState,
} from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { pick } from "@web/core/utils/collections/objects";
import { delay } from "@web/core/utils/concurrency";

import { CropOverlay } from "./crop_overlay.js";
import {
    buildZXingBarcodeDetector,
    isVideoElementReady,
} from "./ZXingBarcodeDetector.js";

export class BarcodeVideoScanner extends Component {
    static template = "web.BarcodeVideoScanner";
    static components = {
        CropOverlay,
    };
    static props = {
        cssClass: { type: String, optional: true },
        facingMode: {
            type: String,
            validate: (fm) => ["environment", "left", "right", "user"].includes(fm),
        },
        close: { type: Function, optional: true },
        onReady: { type: Function, optional: true },
        onResult: Function,
        onError: Function,
        placeholder: { type: String, optional: true },
        delayBetweenScan: { type: Number, optional: true },
    };
    static defaultProps = {
        cssClass: "w-100 h-100",
    };
    /**
     * @override
     */
    setup() {
        this.videoPreviewRef = useRef("videoPreview");
        this.detectorTimeout = null;
        this.stream = null;
        this.detector = null;
        this.overlayInfo = {};
        this.zoomRatio = 1;
        this.scanPaused = false;
        this.state = useState({
            isReady: false,
        });

        onWillStart(async () => {
            let DetectorClass;
            // Use the Barcode Detection API if available; fall back to
            // ZXing (support is still bleeding edge, mainly Chrome/Android).
            if ("BarcodeDetector" in window) {
                DetectorClass = BarcodeDetector;
            } else {
                const ZXing = await import("zxing-library");
                DetectorClass = buildZXingBarcodeDetector(ZXing);
            }
            const formats = await DetectorClass.getSupportedFormats();
            this.detector = new DetectorClass({ formats });
        });

        onMounted(async () => {
            const constraints = {
                video: { facingMode: this.props.facingMode },
                audio: false,
            };

            try {
                this.stream =
                    await browser.navigator.mediaDevices.getUserMedia(constraints);
            } catch (err) {
                const errors = {
                    NotFoundError: _t("No device can be found."),
                    NotAllowedError: _t("Odoo needs your authorization first."),
                };
                const errorMessage = _t("Could not start scanning. %(message)s", {
                    message: errors[err.name] || err.message,
                });
                this.props.onError(new Error(errorMessage));
                return;
            }
            if (!this.videoPreviewRef.el) {
                this.cleanStreamAndTimeout();
                const errorMessage = _t(
                    "Barcode Video Scanner could not be mounted properly.",
                );
                this.props.onError(new Error(errorMessage));
                return;
            }
            /** @type {HTMLVideoElement} */ (this.videoPreviewRef.el).srcObject =
                this.stream;
            const ready = await this.isVideoReady();
            if (!ready) {
                return;
            }
            const { height, width } = getComputedStyle(this.videoPreviewRef.el);
            const divWidth = parseFloat(width);
            const divHeight = parseFloat(height);
            const tracks = this.stream.getVideoTracks();
            if (tracks.length) {
                const [track] = tracks;
                const settings = track.getSettings();
                this.zoomRatio = Math.min(
                    divWidth / settings.width,
                    divHeight / settings.height,
                );
                this.addZoomSlider(track, settings);
            }
            this.detectorTimeout = browser.setTimeout(this.detectCode.bind(this), 100);
        });

        onWillUnmount(() => this.cleanStreamAndTimeout());
    }

    cleanStreamAndTimeout() {
        browser.clearTimeout(this.detectorTimeout);
        this.detectorTimeout = null;
        if (this.stream) {
            this.stream.getTracks().forEach((track) => track.stop());
            this.stream = null;
        }
    }

    isZXingBarcodeDetector() {
        return this.detector?.constructor.name === "ZXingBarcodeDetector";
    }

    /**
     * Check for camera preview element readiness
     *
     * @returns {Promise} resolves when the video element is ready
     */
    async isVideoReady() {
        // FIXME: even if it shouldn't happened, a timeout could be useful here.
        while (!isVideoElementReady(this.videoPreviewRef.el)) {
            await delay(10);
            if (status(this) === "destroyed") {
                return false;
            }
        }
        this.state.isReady = true;
        if (this.props.onReady) {
            this.props.onReady();
        }
        return true;
    }

    onResize(overlayInfo) {
        this.overlayInfo = overlayInfo;
        if (this.isZXingBarcodeDetector()) {
            // TODO need refactoring when ZXing will support multiple result in one scan
            // https://github.com/zxing-js/library/issues/346
            /** @type {any} */ (this.detector).setCropArea(
                this.adaptValuesWithRatio(this.overlayInfo, true),
            );
        }
    }

    /**
     * Attempt to detect codes in the current camera preview's frame
     */
    async detectCode() {
        let barcodeDetected = false;
        let codes = [];
        try {
            codes = await this.detector.detect(
                /** @type {HTMLVideoElement} */ (this.videoPreviewRef.el),
            );
        } catch (err) {
            this.props.onError(err);
        }
        for (const code of codes) {
            if (
                !this.isZXingBarcodeDetector() &&
                this.overlayInfo.x !== undefined &&
                this.overlayInfo.y !== undefined
            ) {
                const { x, y, width, height } = this.adaptValuesWithRatio(
                    code.boundingBox,
                );
                if (
                    x < this.overlayInfo.x ||
                    x + width > this.overlayInfo.x + this.overlayInfo.width ||
                    y < this.overlayInfo.y ||
                    y + height > this.overlayInfo.y + this.overlayInfo.height
                ) {
                    continue;
                }
            }
            barcodeDetected = true;
            this.barcodeDetected(code.rawValue);
            break;
        }
        if (this.stream && (!barcodeDetected || !this.props.delayBetweenScan)) {
            this.detectorTimeout = browser.setTimeout(this.detectCode.bind(this), 100);
        }
    }

    barcodeDetected(barcode) {
        if (this.props.delayBetweenScan && !this.scanPaused) {
            this.scanPaused = true;
            this.detectorTimeout = browser.setTimeout(() => {
                this.scanPaused = false;
                this.detectorTimeout = browser.setTimeout(
                    this.detectCode.bind(this),
                    100,
                );
            }, this.props.delayBetweenScan);
        }
        this.props.onResult(barcode);
    }

    adaptValuesWithRatio(domRect, dividerRatio = false) {
        const newObject = pick(domRect, "x", "y", "width", "height");
        for (const key of Object.keys(newObject)) {
            if (dividerRatio) {
                newObject[key] /= this.zoomRatio;
            } else {
                newObject[key] *= this.zoomRatio;
            }
        }
        return newObject;
    }

    addZoomSlider(track, settings) {
        const zoom = track.getCapabilities().zoom;
        if (zoom?.min !== undefined && zoom?.max !== undefined) {
            const inputElement = document.createElement("input");
            inputElement.type = "range";
            inputElement.min = zoom.min;
            inputElement.max = zoom.max;
            inputElement.step = zoom.step || 1;
            inputElement.value = settings.zoom;
            inputElement.classList.add("align-self-end", "m-5", "z-1");
            inputElement.addEventListener("input", async (event) => {
                await track?.applyConstraints({
                    advanced: [{ zoom: inputElement.value }],
                });
            });
            this.videoPreviewRef.el.parentElement.appendChild(inputElement);
        }
    }
}

/**
 * Check for BarcodeScanner support
 * @returns {boolean}
 */
export function isBarcodeScannerSupported() {
    return Boolean(
        browser.navigator.mediaDevices && browser.navigator.mediaDevices.getUserMedia,
    );
}
