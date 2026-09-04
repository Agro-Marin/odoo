/** @odoo-module native */
import { browser } from "@web/core/browser/browser";

/** Most preferred first. */
const MIMETYPES = [
    "audio/webm;codecs=opus",
    "audio/ogg;codecs=opus",
    "audio/mpeg",
    "audio/webm",
    "audio/wav",
];

export const SEGMENT_MS = 60_000;
const BITRATE = 32_000;
const GAIN = 1 / Math.sqrt(2);

/** @returns {string} */
export function preferredMimetype() {
    const supported = browser.MediaRecorder?.isTypeSupported;
    if (!supported) {
        return "";
    }
    return MIMETYPES.find((type) => browser.MediaRecorder.isTypeSupported(type)) ?? "";
}

/** @returns {boolean} */
export function isRecordingSupported() {
    return Boolean(browser.MediaRecorder && preferredMimetype());
}

export class CallRecorder {
    /** @type {AudioContext} */
    audioContext;
    /** @type {MediaStreamAudioDestinationNode} */
    destination;
    /** @type {MediaRecorder} */
    recorder;
    /** @type {Map<string, MediaStreamAudioSourceNode>} */
    sources = new Map();
    /** @type {Blob[]} */
    chunks = [];
    /** @type {Set<Promise>} */
    pending = new Set();
    recording = false;
    startedAt = 0;
    elapsedMs = 0;
    spanMs = 0;

    /**
     * @param {Object} param0
     * @param {() => MediaStreamTrack|undefined} param0.localTrack
     * @param {() => MediaStream[]} param0.remoteStreams
     * @param {(blob: Blob, startMs: number, endMs: number) => Promise} param0.onSegment
     * @param {number} [param0.segmentMs]
     */
    constructor({ localTrack, remoteStreams, onSegment, segmentMs = SEGMENT_MS }) {
        this.localTrack = localTrack;
        this.remoteStreams = remoteStreams;
        this.onSegment = onSegment;
        this.segmentMs = segmentMs;
        this.mimetype = preferredMimetype();
    }

    start() {
        if (this.recording) {
            return;
        }
        this.audioContext = new browser.AudioContext();
        this.destination = new MediaStreamAudioDestinationNode(this.audioContext, {
            channelCount: 1,
            channelCountMode: "explicit",
            channelInterpretation: "speakers",
        });
        this.recording = true;
        this.elapsedMs = 0;
        this._connectVoices();
        this._recordSegment();
    }

    async stop() {
        if (!this.recording) {
            return;
        }
        this.recording = false;
        browser.clearTimeout(this._timeout);
        await this._closeSegment();
        await Promise.allSettled([...this.pending]);
        for (const source of this.sources.values()) {
            source.disconnect();
        }
        this.sources.clear();
        await this.audioContext?.close();
        this.audioContext = undefined;
        this.destination = undefined;
    }

    _connectVoices() {
        const streams = [];
        const local = this.localTrack();
        if (local) {
            streams.push(new browser.MediaStream([local]));
        }
        streams.push(...this.remoteStreams());
        for (const stream of streams) {
            if (!stream || this.sources.has(stream.id)) {
                continue;
            }
            const source = this.audioContext.createMediaStreamSource(stream);
            source
                .connect(new GainNode(this.audioContext, { gain: GAIN }))
                .connect(this.destination);
            this.sources.set(stream.id, source);
        }
    }

    _recordSegment() {
        // A new recorder per segment, rather than one recorder given a
        // timeslice: a timeslice emits blobs that share one container header,
        // so only the first of them plays on its own, and a segment that
        // cannot be played on its own is not a segment.
        if (!this.recording) {
            return;
        }
        this.chunks = [];
        this.segmentStartMs = this.elapsedMs;
        this.startedAt = Date.now();
        this.recorder = new browser.MediaRecorder(this.destination.stream, {
            audioBitsPerSecond: BITRATE,
            mimeType: this.mimetype || undefined,
        });
        this.recorder.addEventListener("dataavailable", (ev) => {
            if (ev.data?.size) {
                this.chunks.push(ev.data);
            }
        });
        this.recorder.addEventListener("stop", () => this._onSegmentStopped());
        this.recorder.start();
        this._timeout = browser.setTimeout(() => this._rollSegment(), this.segmentMs);
    }

    _rollSegment() {
        this._connectVoices();
        if (this.recorder?.state === "recording") {
            this.spanMs = Math.max(Date.now() - this.startedAt, 1);
            this.recorder.stop();
        }
    }

    async _closeSegment() {
        if (this.recorder?.state !== "recording") {
            return;
        }
        const stopped = new Promise((resolve) => {
            this.recorder.addEventListener("stop", resolve, { once: true });
        });
        this.spanMs = Math.max(Date.now() - this.startedAt, 1);
        this.recorder.stop();
        await stopped;
    }

    _onSegmentStopped() {
        const endMs = this.segmentStartMs + this.spanMs;
        const blob = new Blob(this.chunks, { type: this.mimetype || "audio/webm" });
        this.elapsedMs = endMs;
        if (blob.size) {
            const upload = Promise.resolve(
                this.onSegment(
                    blob,
                    Math.round(this.segmentStartMs),
                    Math.round(endMs),
                ),
            );
            this.pending.add(upload);
            upload.finally(() => this.pending.delete(upload));
        }
        if (this.recording) {
            this._recordSegment();
        }
    }
}
