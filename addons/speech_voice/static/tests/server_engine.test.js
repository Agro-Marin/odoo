// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { onRpc, makeMockEnv, patchWithCleanup } from "@web/../tests/web_test_helpers";
import {
    END_OF_SPEECH_S,
    MAX_UTTERANCE_S,
    serverEngine,
    UtteranceRecorder,
} from "@speech_voice/server_engine";

describe.current.tags("headless");

const RATE = 1000;

/**
 * @param {number} seconds
 * @param {number} [amplitude]
 */
function tone(seconds, amplitude = 0.5) {
    return Float32Array.from({ length: seconds * RATE }, (_, index) =>
        index % 2 ? amplitude : -amplitude,
    );
}

function recorder() {
    const ended = [];
    const chunks = [];
    const instance = new UtteranceRecorder((chunk) => chunks.push(chunk));
    instance.sampleRate = RATE;
    instance.onEnd = () => ended.push(instance.length / RATE);
    return { instance, ended, chunks };
}

test("an utterance ends at the first pause after speech", () => {
    const { instance, ended } = recorder();
    instance.feed(tone(2, 0));
    expect(ended).toEqual([]);
    instance.feed(tone(1));
    instance.feed(tone(END_OF_SPEECH_S / 2, 0));
    expect(ended).toEqual([]);
    instance.feed(tone(END_OF_SPEECH_S / 2, 0));
    expect(ended).toEqual([2 + 1 + END_OF_SPEECH_S]);
});

test("an utterance without a pause ends at the maximum", () => {
    const { instance, ended } = recorder();
    for (let second = 0; second < MAX_UTTERANCE_S; second++) {
        instance.feed(tone(1));
    }
    expect(ended).toEqual([MAX_UTTERANCE_S]);
});

test("the recording is sent whole, as one wav", () => {
    const { instance, chunks } = recorder();
    instance.feed(tone(1));
    instance.feed(tone(1));
    instance.cut();
    expect(chunks).toHaveLength(1);
    expect(chunks[0].durationS).toBe(2);
    expect(chunks[0].mimetype).toBe("audio/wav");
});

test("the server says whether it may hear commands", async () => {
    patchWithCleanup(navigator, {
        mediaDevices: /** @type {any} */ ({ getUserMedia: async () => ({}) }),
    });
    let available = true;
    onRpc("/speech_voice/available", () => ({ available }));
    await makeMockEnv();
    expect(await serverEngine.available("es-MX")).toBe(true);
    available = false;
    expect(await serverEngine.available("es-MX")).toBe(false);
});
