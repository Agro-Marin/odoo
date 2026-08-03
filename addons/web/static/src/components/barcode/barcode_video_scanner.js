// @ts-check
/** @odoo-module native */

/** @module @web/components/barcode/barcode_video_scanner */

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
import { _t } from "@web/core/translation";
import { pick } from "@web/core/utils/collections/objects";
import { delay } from "@web/core/utils/concurrency";

import { CropOverlay } from "./crop_overlay.js";
import {
    buildZXingBarcodeDetector,
    isVideoElementReady,
} from "./ZXingBarcodeDetector.js";

const MAX_CONSECUTIVE_DETECT_ERRORS = 5;

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
        this.consecutiveDetectErrors = 0;
        this.zoomTrack = null;
        this.state = useState({
            isReady: false,
            /** @type {{min: number, max: number, step: number, value: number} | null} */
            zoom: null,
        });

        onWillStart(async () => {
            let DetectorClass;
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
     * @returns {Promise}
     */
    async isVideoReady() {
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
            /** @type {any} */ (this.detector).setCropArea(
                this.adaptValuesWithRatio(this.overlayInfo, true),
            );
        }
    }

    async detectCode() {
        let barcodeDetected = false;
        let codes = [];
        try {
            codes = await this.detector.detect(
                /** @type {HTMLVideoElement} */ (this.videoPreviewRef.el),
            );
            this.consecutiveDetectErrors = 0;
        } catch (err) {
            this.consecutiveDetectErrors++;
            if (this.consecutiveDetectErrors >= MAX_CONSECUTIVE_DETECT_ERRORS) {
                this.props.onError(err);
                this.cleanStreamAndTimeout();
                return;
            }
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

    /**
     * @param {MediaStreamTrack} track
     * @param {MediaTrackSettings} settings
     */
    addZoomSlider(track, settings) {
        const zoom = track.getCapabilities?.().zoom;
        if (zoom?.min === undefined || zoom?.max === undefined) {
            return;
        }
        this.zoomTrack = track;
        this.state.zoom = {
            min: zoom.min,
            max: zoom.max,
            step: zoom.step || 1,
            value: settings.zoom ?? zoom.min,
        };
    }

    /**
     * @param {Event} ev
     */
    onZoomInput(ev) {
        const value = Number(/** @type {HTMLInputElement} */ (ev.target).value);
        this.state.zoom.value = value;
        this.zoomTrack?.applyConstraints({ advanced: [{ zoom: value }] });
    }
}

/**
 * @returns {boolean}
 */
export function isBarcodeScannerSupported() {
    return Boolean(
        browser.navigator.mediaDevices && browser.navigator.mediaDevices.getUserMedia,
    );
}
