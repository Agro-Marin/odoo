import { CallRecorder, preferredMimetype } from "@mail_speech/call_recorder";
import { describe, expect, test } from "@odoo/hoot";
import { advanceTime } from "@odoo/hoot-mock";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";

describe.current.tags("desktop");

class MockMediaRecorder {
    static instances = [];
    static isTypeSupported = (type) => type === "audio/webm;codecs=opus";

    constructor(stream, options) {
        this.stream = stream;
        this.options = options;
        this.state = "inactive";
        this.listeners = {};
        MockMediaRecorder.instances.push(this);
    }

    addEventListener(name, handler) {
        (this.listeners[name] ??= []).push(handler);
    }

    start() {
        this.state = "recording";
    }

    stop() {
        this.state = "inactive";
        for (const handler of this.listeners.dataavailable ?? []) {
            handler({ data: new Blob(["audio"], { type: "audio/webm" }) });
        }
        for (const handler of this.listeners.stop ?? []) {
            handler();
        }
    }
}

class MockAudioContext {
    closed = false;
    createMediaStreamSource(stream) {
        return {
            stream,
            connect: (node) => ({ connect: () => node }),
            disconnect: () => {},
        };
    }
    close() {
        this.closed = true;
        return Promise.resolve();
    }
}

function patchRecordingBrowser() {
    MockMediaRecorder.instances = [];
    patchWithCleanup(browser, {
        MediaRecorder: MockMediaRecorder,
        AudioContext: MockAudioContext,
        MediaStream: class {
            constructor(tracks) {
                this.id = `local-${tracks[0]?.id ?? "none"}`;
            }
        },
    });
    patchWithCleanup(globalThis, {
        MediaStreamAudioDestinationNode: class {
            stream = { id: "mixed" };
        },
        GainNode: class {
            connect() {
                return this;
            }
        },
    });
}

function makeRecorder(onSegment, { segmentMs = 1000 } = {}) {
    return new CallRecorder({
        localTrack: () => ({ id: "mic", kind: "audio" }),
        remoteStreams: () => [{ id: "remote-1" }],
        onSegment,
        segmentMs,
    });
}

describe("preferred format", () => {
    test("the first supported container is chosen", () => {
        patchRecordingBrowser();
        expect(preferredMimetype()).toBe("audio/webm;codecs=opus");
    });

    test("no MediaRecorder means no recording", () => {
        patchWithCleanup(browser, { MediaRecorder: undefined });
        expect(preferredMimetype()).toBe("");
    });
});

describe("segments", () => {
    test("a segment is emitted with the span it covers", async () => {
        patchRecordingBrowser();
        const segments = [];
        const recorder = makeRecorder((blob, startMs, endMs) =>
            segments.push({ size: blob.size, startMs, endMs }),
        );
        recorder.start();
        await advanceTime(1000);
        expect(segments).toHaveLength(1);
        expect(segments[0].startMs).toBe(0);
        expect(segments[0].endMs).toBeGreaterThan(900);
        expect(segments[0].endMs).toBeLessThan(1500);
        await recorder.stop();
    });

    test("each segment is its own recorder, so each file plays alone", async () => {
        patchRecordingBrowser();
        const recorder = makeRecorder(() => {});
        recorder.start();
        await advanceTime(1000);
        await advanceTime(1000);
        expect(MockMediaRecorder.instances.length).toBeGreaterThan(1);
        await recorder.stop();
    });

    test("segments run back to back with no gap and no overlap", async () => {
        patchRecordingBrowser();
        const segments = [];
        const recorder = makeRecorder((blob, startMs, endMs) =>
            segments.push([startMs, endMs]),
        );
        recorder.start();
        await advanceTime(1000);
        await advanceTime(1000);
        await recorder.stop();
        expect(segments.length).toBeGreaterThan(1);
        expect(segments[1][0]).toBe(segments[0][1]);
    });

    test("stopping emits what was recorded so far", async () => {
        patchRecordingBrowser();
        const segments = [];
        const recorder = makeRecorder(() => segments.push(1));
        recorder.start();
        await advanceTime(400);
        await recorder.stop();
        expect(segments).toHaveLength(1);
    });

    test("stopping releases the audio context", async () => {
        patchRecordingBrowser();
        const recorder = makeRecorder(() => {});
        recorder.start();
        const context = recorder.audioContext;
        await recorder.stop();
        expect(context.closed).toBe(true);
        expect(recorder.recording).toBe(false);
    });

    test("a voice joining mid-call is mixed in without restarting the take", async () => {
        patchRecordingBrowser();
        let remotes = [{ id: "remote-1" }];
        const recorder = new CallRecorder({
            localTrack: () => ({ id: "mic" }),
            remoteStreams: () => remotes,
            onSegment: () => {},
            segmentMs: 1000,
        });
        recorder.start();
        expect(recorder.sources.size).toBe(2);
        remotes = [{ id: "remote-1" }, { id: "remote-2" }];
        await advanceTime(1000);
        expect(recorder.sources.size).toBe(3);
        await recorder.stop();
    });

    test("stopping waits for the segment upload to finish", async () => {
        patchRecordingBrowser();
        let resolveUpload;
        const finished = [];
        const recorder = makeRecorder(
            () =>
                new Promise((resolve) => {
                    resolveUpload = () => {
                        finished.push(1);
                        resolve();
                    };
                }),
        );
        recorder.start();
        await advanceTime(400);
        let stopped = false;
        const stopping = recorder.stop().then(() => (stopped = true));
        await Promise.resolve();
        expect(stopped).toBe(false);
        resolveUpload();
        await stopping;
        expect(stopped).toBe(true);
        expect(finished).toHaveLength(1);
    });

    test("starting twice does not open a second take", async () => {
        patchRecordingBrowser();
        const recorder = makeRecorder(() => {});
        recorder.start();
        const opened = MockMediaRecorder.instances.length;
        recorder.start();
        expect(MockMediaRecorder.instances).toHaveLength(opened);
        await recorder.stop();
    });
});
