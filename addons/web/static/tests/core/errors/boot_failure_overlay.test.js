// @ts-check

import { afterEach, describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { paintBootFailureOverlay } from "@web/core/errors/boot_failure_overlay";

describe.current.tags("headless");

afterEach(removeOverlays);

function overlays() {
    return document.querySelectorAll(".o_boot_failure");
}

function removeOverlays() {
    for (const el of overlays()) {
        el.remove();
    }
}

function stubBeacon() {
    /** @type {any[]} */
    const sent = [];
    patchWithCleanup(globalThis.navigator, {
        sendBeacon(url, blob) {
            sent.push({ url, blob });
            return true;
        },
    });
    return sent;
}

describe("paintBootFailureOverlay", () => {
    test("paints an alert with a title, an explanation and a reload button", () => {
        stubBeacon();
        paintBootFailureOverlay(new Error("boom"));

        expect(overlays()).toHaveLength(1);
        const overlay = overlays()[0];
        expect(overlay.getAttribute("role")).toBe("alert");
        expect(overlay.querySelector("h1")?.textContent).toBe("Something went wrong");
        expect(overlay.querySelector("p")?.textContent).toInclude("could not start");
        expect(overlay.querySelector("button")?.textContent).toBe("Reload");
    });

    test("is idempotent — a second failure does not stack overlays", () => {
        stubBeacon();
        paintBootFailureOverlay(new Error("first"));
        paintBootFailureOverlay(new Error("second"));
        expect(overlays()).toHaveLength(1);
    });

    test("reports the failure before painting, and keeps reporting repeats", () => {
        const sent = stubBeacon();
        paintBootFailureOverlay(new Error("first"));
        paintBootFailureOverlay(new Error("second"));
        expect(sent).toHaveLength(2);
        expect(sent[0].url).toBe("/web/observability/js_error");
    });

    test("the beacon carries the message, the phase and a bounded stack", async () => {
        const sent = stubBeacon();
        const error = new Error("kaboom");
        error.stack = "x".repeat(9000);
        paintBootFailureOverlay(error);

        const payload = JSON.parse(await sent[0].blob.text());
        expect(payload.phase).toBe("boot_mount_failed");
        expect(payload.kind).toBe("error");
        expect(payload.message).toBe("kaboom");
        expect(payload.stack).toHaveLength(4096);
    });

    test("an explicit phase overrides the mount default", async () => {
        const sent = stubBeacon();
        paintBootFailureOverlay(new Error("kaboom"), "boot_prologue");
        const payload = JSON.parse(await sent[0].blob.text());
        expect(payload.phase).toBe("boot_prologue");
    });

    test("reports the cause, which is where OWL puts the real error", async () => {
        const sent = stubBeacon();
        const cause = new Error("localization parameters are not ready yet");
        paintBootFailureOverlay(
            new Error("An error occured in the owl lifecycle", { cause }),
        );

        const payload = JSON.parse(await sent[0].blob.text());
        expect(payload.message).toBe("An error occured in the owl lifecycle");
        expect(JSON.stringify(payload)).toInclude("localization parameters");
    });

    test("never throws, whatever it is handed", () => {
        stubBeacon();
        for (const value of [undefined, null, "a string", 0, { nope: true }]) {
            expect(() => paintBootFailureOverlay(value)).not.toThrow();
            removeOverlays();
        }
    });

    test("falls back to a placeholder when the error carries no message", async () => {
        const sent = stubBeacon();
        paintBootFailureOverlay(undefined);
        const payload = JSON.parse(await sent[0].blob.text());
        expect(payload.message).toBe("(no message)");
    });

    test("survives a browser with no sendBeacon at all", () => {
        patchWithCleanup(globalThis.navigator, { sendBeacon: undefined });
        expect(() => paintBootFailureOverlay(new Error("boom"))).not.toThrow();
        expect(overlays()).toHaveLength(1);
    });
});
