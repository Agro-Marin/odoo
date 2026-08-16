/** @odoo-module native */
import { closeStream } from "@mail/utils/common/misc";
import { browser } from "@web/core/browser/browser";
const FPS = 30;

/**
 * @param {CanvasImageSource & {width: number, height: number}} image
 * @param {number} blurAmount
 * @param {HTMLCanvasElement} canvas
 */
function drawAndBlurImageOnCanvas(image, blurAmount, canvas) {
    if (canvas.width !== image.width) {
        canvas.width = image.width;
    }
    if (canvas.height !== image.height) {
        canvas.height = image.height;
    }
    const ctx = canvas.getContext("2d");
    if (blurAmount === 0) {
        ctx.drawImage(image, 0, 0, image.width, image.height);
        return;
    }
    ctx.clearRect(0, 0, image.width, image.height);
    ctx.save();
    ctx.filter = `blur(${blurAmount}px)`;
    ctx.drawImage(image, 0, 0, image.width, image.height);
    ctx.restore();
}

export class BlurManager {
    canvas = document.createElement("canvas");
    canvasBlur = document.createElement("canvas");
    canvasMask = document.createElement("canvas");
    /** @type {MediaStream} */
    canvasStream;
    isVideoDataLoaded = false;
    /** @type {(reason?: any) => void} */
    rejectStreamPromise;
    /** @type {(stream: MediaStream) => void} */
    resolveStreamPromise;
    selfieSegmentation = new window.SelfieSegmentation({
        /** @param {string} file */
        locateFile: (file) =>
            `https://cdn.jsdelivr.net/npm/@mediapipe/selfie_segmentation@0.1/${file}`,
    });
    /**
     * @type {Promise<MediaStream>}
     */
    stream;
    video = document.createElement("video");
    /** @type {Worker|null} */
    worker;

    /**
     * @param {MediaStream} stream
     * @param {Object} [options]
     * @param {number} [options.backgroundBlur=10]
     * @param {number} [options.edgeBlur=10]
     * @param {number} [options.modelSelection=1]
     * @param {boolean} [options.selfieMode=false]
     */
    constructor(
        stream,
        {
            backgroundBlur = 10,
            edgeBlur = 10,
            modelSelection = 1,
            selfieMode = false,
        } = {},
    ) {
        this.edgeBlur = edgeBlur;
        this.backgroundBlur = backgroundBlur;
        this._onVideoPlay = this._onVideoPlay.bind(this);
        this.video.addEventListener("loadeddata", this._onVideoPlay);
        this.canvas.getContext("2d");
        this.canvasStream = this.canvas.captureStream();
        let rejectStreamPromise;
        let resolveStreamPromise;
        Object.assign(this, {
            stream: new Promise((resolve, reject) => {
                rejectStreamPromise = reject;
                resolveStreamPromise = resolve;
            }),
            rejectStreamPromise,
            resolveStreamPromise,
        });
        try {
            this.worker = new Worker(
                "/mail/static/src/discuss/call/common/tick_worker.js",
            );
            this.worker.onmessage = /** @param {MessageEvent} e */ (e) =>
                this._handleWorkerMessage(e);
            this.worker.onerror = () => {
                this._terminateWorker();
                this._requestFrame();
            };
        } catch {
            this.worker = null;
        }
        this.video.srcObject = stream;
        this.video.load();
        this.selfieSegmentation.setOptions({
            selfieMode,
            modelSelection,
        });
        this.selfieSegmentation.onResults(
            /** @param {{image: CanvasImageSource, segmentationMask: CanvasImageSource}} r */
            (r) => this._onSelfieSegmentationResults(r),
        );
        this.video.autoplay = true;
        Promise.resolve(this.video.play()).catch(() => {});
    }

    close() {
        this.video.removeEventListener("loadeddata", this._onVideoPlay);
        this.video.srcObject = null;
        this.isVideoDataLoaded = false;
        Promise.resolve(this.selfieSegmentation.close?.()).catch(() => {});
        closeStream(this.canvasStream);
        this.canvasStream = null;
        this._terminateWorker();
        if (this.rejectStreamPromise) {
            this.rejectStreamPromise(
                new Error(
                    "The source stream was removed before the beginning of the blur process",
                ),
            );
        }
    }

    /** @param {MessageEvent} e */
    async _handleWorkerMessage(e) {
        if (e.data.command === "tick") {
            await this._onFrame();
            this.worker?.postMessage({ command: "tock" });
        }
    }

    _terminateWorker() {
        if (this.worker) {
            this.worker.postMessage({ command: "stop" });
            this.worker.terminate();
        }
        this.worker = null;
    }

    /**
     * @param {CanvasImageSource} image
     * @param {GlobalCompositeOperation} compositeOperation
     */
    _drawWithCompositing(image, compositeOperation) {
        this.canvas.getContext("2d").globalCompositeOperation = compositeOperation;
        this.canvas.getContext("2d").drawImage(image, 0, 0);
    }

    _onVideoPlay() {
        this.isVideoDataLoaded = true;
        if (this.worker) {
            this.worker.postMessage({ command: "start", fps: FPS });
        } else {
            this._requestFrame();
        }
    }

    async _onFrame() {
        if (!this.selfieSegmentation) {
            return;
        }
        if (!this.video) {
            return;
        }
        if (!this.isVideoDataLoaded) {
            return;
        }
        try {
            await this.selfieSegmentation.send({ image: this.video });
        } catch (error) {
            this.isVideoDataLoaded = false;
            if (this.resolveStreamPromise) {
                this.rejectStreamPromise(error);
                this.resolveStreamPromise = null;
            }
        }
    }

    /**
     * @param {Object} results
     * @param {CanvasImageSource & {width: number, height: number}} results.image
     * @param {CanvasImageSource} results.segmentationMask
     */
    _onSelfieSegmentationResults(results) {
        drawAndBlurImageOnCanvas(results.image, this.backgroundBlur, this.canvasBlur);
        if (this.canvas.width !== this.canvasBlur.width) {
            this.canvas.width = this.canvasBlur.width;
        }
        if (this.canvas.height !== this.canvasBlur.height) {
            this.canvas.height = this.canvasBlur.height;
        }
        drawAndBlurImageOnCanvas(
            results.segmentationMask,
            this.edgeBlur,
            this.canvasMask,
        );
        const ctx = this.canvas.getContext("2d");
        ctx.save();
        ctx.drawImage(results.image, 0, 0, this.canvas.width, this.canvas.height);
        this._drawWithCompositing(this.canvasMask, "destination-in");
        this._drawWithCompositing(this.canvasBlur, "destination-over");
        ctx.restore();
        if (this.resolveStreamPromise) {
            this.resolveStreamPromise(this.canvasStream);
            this.resolveStreamPromise = null;
        }
    }

    _requestFrame() {
        if (!this.isVideoDataLoaded) {
            return;
        }
        browser.requestAnimationFrame(async () => {
            await this._onFrame();
            if (!this.worker) {
                browser.setTimeout(() => this._requestFrame(), Math.floor(1000 / FPS));
            }
        });
    }
}
