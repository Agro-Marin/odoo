import { LocalMediaController } from "@mail/discuss/call/common/local_media_controller";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";

/**
 * A real (but content-free) MediaStream to stand in for the blurred output.
 * It must be a genuine MediaStream because CallPreview's reactive effect binds
 * it to `<video>.srcObject`, which rejects plain objects. A canvas capture
 * stream carries a real, stoppable video track, so the teardown's
 * `closeStream()` flips its `readyState` to "ended" for assertions.
 */
function makeMockBlurStream() {
    const canvas = document.createElement("canvas");
    canvas.getContext("2d"); // some browsers require a context before captureStream()
    return canvas.captureStream();
}

/**
 * Test double for `@mail/discuss/call/common/blur_manager`'s BlurManager.
 *
 * The real BlurManager instantiates `window.SelfieSegmentation` (MediaPipe,
 * fetched from a CDN) and resolves its output `stream` only after a Web Worker
 * + a `<video>` "loadeddata" chain has produced a segmented frame — none of
 * which is available (or fires for a mock camera stream) under hoot. This
 * mirrors only the surface consumed by `CallPreview` and `LocalMediaController`:
 * an already-resolved `stream`, mutable `edgeBlur`/`backgroundBlur`, and an
 * observable `close()`.
 */
export class MockBlurManager {
    /** @type {string[]} recorded method calls, for assertions */
    calls = [];
    closed = false;
    edgeBlur;
    backgroundBlur;
    /** the source (camera) stream passed to the constructor */
    sourceStream;
    /** the resolved blurred stream, exposed so tests can assert teardown */
    blurStream = makeMockBlurStream();
    /** Promise<MediaStream>, mirroring the real BlurManager.stream */
    stream = Promise.resolve(this.blurStream);

    constructor(sourceStream, { backgroundBlur, edgeBlur } = {}) {
        this.sourceStream = sourceStream;
        this.backgroundBlur = backgroundBlur;
        this.edgeBlur = edgeBlur;
    }

    close() {
        this.calls.push("close");
        this.closed = true;
    }
}

/**
 * Route every BlurManager construction (both `rtc.applyBlurEffect` and
 * `LocalMediaController`'s internal `_updateLocalVideo` use funnel through
 * `LocalMediaController.applyBlurEffect`) through a `MockBlurManager`, so blur
 * can be exercised in tests without MediaPipe.
 *
 * @returns {MockBlurManager[]} the managers created so far, newest last
 */
export function mockBlurManager() {
    const managers = [];
    patchWithCleanup(LocalMediaController.prototype, {
        async applyBlurEffect(sourceStream) {
            const settings = this.hooks.getSettings();
            const manager = new MockBlurManager(sourceStream, {
                backgroundBlur: settings.backgroundBlurAmount,
                edgeBlur: settings.edgeBlurAmount,
            });
            managers.push(manager);
            return manager;
        },
    });
    return managers;
}
