/** @odoo-module native */
import { closeStream } from "@mail/utils/common/misc";
import { browser } from "@web/core/browser/browser";
const FPS = 30; // Frames per second for the blurred background stream

function drawAndBlurImageOnCanvas(image, blurAmount, canvas) {
    // Assigning canvas.width/height reallocates the backing store and resets the
    // 2D context, so only do it when the dimensions actually change (camera
    // resolution is stable across the ~30fps stream). getContext is fetched once
    // instead of up to five times per frame.
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
    // FIXME : Does not work on safari https://bugs.webkit.org/show_bug.cgi?id=198416
    ctx.filter = `blur(${blurAmount}px)`;
    ctx.drawImage(image, 0, 0, image.width, image.height);
    ctx.restore();
}

export class BlurManager {
    canvas = document.createElement("canvas");
    canvasBlur = document.createElement("canvas");
    canvasMask = document.createElement("canvas");
    canvasStream;
    isVideoDataLoaded = false;
    rejectStreamPromise;
    resolveStreamPromise;
    selfieSegmentation = new window.SelfieSegmentation({
        locateFile: (file) =>
            `https://cdn.jsdelivr.net/npm/@mediapipe/selfie_segmentation@0.1/${file}`,
    });
    /**
     * Promise or undefined, based on the input stream, resolved when selfieSegmentation has started painting on the canvas,
     * resolves into a web.MediaStream that is the blurred version of the input stream.
     */
    stream;
    video = document.createElement("video");
    worker;

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
        this.canvas.getContext("2d"); // canvas.captureStream() doesn't work on firefox before getContext() is called.
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
            this.worker.onmessage = (e) => this._handleWorkerMessage(e);
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
        this.selfieSegmentation.onResults((r) => this._onSelfieSegmentationResults(r));
        this.video.autoplay = true;
        Promise.resolve(this.video.play()).catch(() => {});
    }

    close() {
        this.video.removeEventListener("loadeddata", this._onVideoPlay);
        this.video.srcObject = null;
        this.isVideoDataLoaded = false;
        // close(), not reset(): each BlurManager constructs its own
        // SelfieSegmentation, so a kept WASM context leaks one heap per
        // camera/blur toggle for the lifetime of the tab
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

    /**
     * @private
     * @param {MessageEvent} e
     */
    async _handleWorkerMessage(e) {
        if (e.data.command === "tick") {
            await this._onFrame();
            // close() can run during the awaited frame: _terminateWorker
            // nulled the slot and posting would throw
            this.worker?.postMessage({ command: "tock" });
        }
    }

    /**
     * @private
     */
    _terminateWorker() {
        if (this.worker) {
            this.worker.postMessage({ command: "stop" });
            this.worker.terminate();
        }
        this.worker = null;
    }

    _drawWithCompositing(image, compositeOperation) {
        this.canvas.getContext("2d").globalCompositeOperation = compositeOperation;
        this.canvas.getContext("2d").drawImage(image, 0, 0);
    }

    /**
     * @private
     */
    _onVideoPlay() {
        this.isVideoDataLoaded = true;
        if (this.worker) {
            this.worker.postMessage({ command: "start", fps: FPS });
        } else {
            this._requestFrame();
        }
    }

    /**
     * @private
     */
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
            // the mediapipe model/WASM files load at runtime from a CDN:
            // unreachable (offline, CSP, air-gapped deployment) means send()
            // rejects and no result callback ever fires. Without this, the
            // `stream` promise stays pending FOREVER — setVideo hangs with
            // the camera LED on — and each frame is an unhandled rejection.
            this.isVideoDataLoaded = false; // stop the tick/rAF loop
            if (this.resolveStreamPromise) {
                this.rejectStreamPromise(error);
                this.resolveStreamPromise = null;
            }
        }
    }

    /**
     * @private
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

    /**
     * @private
     */
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
