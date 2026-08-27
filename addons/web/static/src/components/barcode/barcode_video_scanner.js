// @ts-check
/** @odoo-module native */

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
const DETECT_INTERVAL = 100;

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
    /** @type {import("@odoo/owl").Ref<HTMLVideoElement>} */
    videoPreviewRef;
    /** @type {any} */
    detectorTimeout = null;
    /** @type {MediaStream | null} */
    stream = null;
    /** @type {any} */
    detector = null;
    /** @type {{ x?: number, y?: number, width?: number, height?: number }} */
    overlayInfo = {};
    zoomRatio = 1;
    scanPaused = false;
    consecutiveDetectErrors = 0;
    /** @type {MediaStreamTrack | null} */
    zoomTrack = null;
    /** @type {{ isReady: boolean, zoom: {min: number, max: number, step: number, value: number} | null }} */
    state;

    /**
     * @override
     */
    setup() {
        this.videoPreviewRef = /** @type {any} */ (useRef("videoPreview"));
        this.state = useState({
            isReady: false,
            /** @type {{min: number, max: number, step: number, value: number} | null} */
            zoom: null,
        });

        onWillStart(async () => {
            let DetectorClass = browser.BarcodeDetector;
            if (!DetectorClass) {
                const ZXing = await import("zxing-library");
                DetectorClass = buildZXingBarcodeDetector(ZXing);
            }
            const formats = await DetectorClass.getSupportedFormats();
            this.detector = new DetectorClass({ formats });
        });

        onMounted(() => this.startScanning());

        onWillUnmount(() => this.cleanStreamAndTimeout());
    }

    /**
     * Acquires the camera and starts the detection loop. Every failure path here
     * has to report through `props.onError` rather than throw: the caller renders
     * a message beside the dead preview, and an unhandled rejection out of
     * `onMounted` would leave it showing a black rectangle instead.
     * @returns {Promise<void>}
     */
    async startScanning() {
        const stream = await this.requestStream();
        if (!stream) {
            return;
        }
        this.stream = stream;
        if (status(this) === "destroyed") {
            this.cleanStreamAndTimeout();
            return;
        }
        if (!this.videoPreviewRef.el) {
            this.cleanStreamAndTimeout();
            this.props.onError(
                new Error(_t("Barcode Video Scanner could not be mounted properly.")),
            );
            return;
        }
        /** @type {HTMLVideoElement} */ (this.videoPreviewRef.el).srcObject =
            this.stream;
        if (!(await this.isVideoReady())) {
            return;
        }
        if (this.videoPreviewRef.el.paused) {
            await this.videoPreviewRef.el.play();
        }
        this.setUpZoom(stream);
        this.detectorTimeout = browser.setTimeout(
            this.detectCode.bind(this),
            DETECT_INTERVAL,
        );
    }

    /**
     * @returns {Promise<MediaStream | null>} null once the error is reported
     */
    async requestStream() {
        try {
            return await browser.navigator.mediaDevices.getUserMedia({
                video: { facingMode: this.props.facingMode },
                audio: false,
            });
        } catch (err) {
            if (status(this) === "destroyed") {
                return null;
            }
            const errors = {
                NotFoundError: _t("No device can be found."),
                NotAllowedError: _t("Odoo needs your authorization first."),
            };
            this.props.onError(
                new Error(
                    _t("Could not start scanning. %(message)s", {
                        message: errors[err.name] || err.message,
                    }),
                ),
            );
            return null;
        }
    }

    /**
     * The crop overlay works in displayed pixels and the detector in camera ones,
     * so the ratio between them has to be known before either can be trusted.
     * @param {MediaStream} stream
     */
    setUpZoom(stream) {
        if (!this.videoPreviewRef.el) {
            return;
        }
        const { height, width } = getComputedStyle(this.videoPreviewRef.el);
        const [track] = stream.getVideoTracks();
        const settings = track?.getSettings();
        if (!settings?.width || !settings.height) {
            return;
        }
        this.zoomRatio = Math.min(
            parseFloat(width) / settings.width,
            parseFloat(height) / settings.height,
        );
        this.addZoomSlider(track, settings);
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
        return Boolean(this.detector?.constructor.cropsAtSource);
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
            const overlay = this.overlayInfo;
            if (
                !this.isZXingBarcodeDetector() &&
                overlay.x !== undefined &&
                overlay.y !== undefined &&
                overlay.width !== undefined &&
                overlay.height !== undefined
            ) {
                const { x, y, width, height } = this.adaptValuesWithRatio(
                    code.boundingBox,
                );
                if (
                    x < overlay.x ||
                    x + width > overlay.x + overlay.width ||
                    y < overlay.y ||
                    y + height > overlay.y + overlay.height
                ) {
                    continue;
                }
            }
            barcodeDetected = true;
            this.barcodeDetected(code.rawValue);
            break;
        }
        if (this.stream && (!barcodeDetected || !this.props.delayBetweenScan)) {
            this.detectorTimeout = browser.setTimeout(
                this.detectCode.bind(this),
                DETECT_INTERVAL,
            );
        }
    }

    barcodeDetected(barcode) {
        if (this.props.delayBetweenScan && !this.scanPaused) {
            this.scanPaused = true;
            this.detectorTimeout = browser.setTimeout(() => {
                this.scanPaused = false;
                this.detectorTimeout = browser.setTimeout(
                    this.detectCode.bind(this),
                    DETECT_INTERVAL,
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
        if (!this.state.zoom) {
            return;
        }
        const value = Number(/** @type {HTMLInputElement} */ (ev.target).value);
        this.state.zoom.value = value;
        this.zoomTrack?.applyConstraints(
            /** @type {any} */ ({ advanced: [{ zoom: value }] }),
        );
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
