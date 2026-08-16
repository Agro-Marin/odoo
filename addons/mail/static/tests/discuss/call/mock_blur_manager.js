import { LocalMediaController } from "@mail/discuss/call/common/local_media_controller";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";

function makeMockBlurStream() {
    const canvas = document.createElement("canvas");
    canvas.getContext("2d");
    return canvas.captureStream();
}

export class MockBlurManager {
    /** @type {string[]} */
    calls = [];
    closed = false;
    edgeBlur;
    backgroundBlur;
    sourceStream;
    blurStream = makeMockBlurStream();
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

/** @returns {MockBlurManager[]} */
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
