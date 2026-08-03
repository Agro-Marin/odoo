// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    getService,
    makeMockEnv,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { hotkeyService } from "@web/core/hotkeys/hotkey_service";

describe.current.tags("headless");

describe("getActiveHotkey physical-key remapping", () => {
    test("digit-row symbols remap to the physical digit", () => {
        expect(getActiveHotkey(/** @type {any} */ ({ key: "@", code: "Digit2" }))).toBe(
            "2",
        );
        expect(getActiveHotkey(/** @type {any} */ ({ key: "é", code: "Digit2" }))).toBe(
            "2",
        );
    });

    test("non-latin layouts remap letters to the physical key", () => {
        expect(getActiveHotkey(/** @type {any} */ ({ key: "щ", code: "KeyO" }))).toBe(
            "o",
        );
    });

    test("a produced character that is itself a registrable hotkey is kept", () => {
        expect(getActiveHotkey(/** @type {any} */ ({ key: "<", code: "Digit2" }))).toBe(
            "<",
        );
        expect(getActiveHotkey(/** @type {any} */ ({ key: "a", code: "KeyQ" }))).toBe(
            "a",
        );
    });

    test("plain digits and letters are unchanged", () => {
        expect(getActiveHotkey(/** @type {any} */ ({ key: "2", code: "Digit2" }))).toBe(
            "2",
        );
        expect(getActiveHotkey(/** @type {any} */ ({ key: "a", code: "KeyA" }))).toBe(
            "a",
        );
    });

    test("modifiers still combine with the remapped key", () => {
        expect(
            getActiveHotkey(
                /** @type {any} */ ({ key: "!", code: "Digit1", shiftKey: true }),
            ),
        ).toBe("shift+1");
    });
});

describe("getActiveHotkey never reports a modifier as the pressed key", () => {
    // MODIFIERS is Odoo's CHORD vocabulary (the prefixes a registered hotkey may
    // carry), not the set of physical modifier key names. Filtering the pressed
    // key against it meant every modifier outside that vocabulary was appended
    // as if it were a character: holding Meta alone produced the hotkey "meta".
    test("bare Meta produces no key part", () => {
        expect(
            getActiveHotkey(/** @type {any} */ ({ key: "Meta", metaKey: true })),
        ).toBe("");
    });

    test("other non-chord modifiers produce no key part either", () => {
        for (const key of ["AltGraph", "CapsLock", "NumLock", "ScrollLock", "Fn"]) {
            expect(getActiveHotkey(/** @type {any} */ ({ key }))).toBe("", {
                message: `bare ${key}`,
            });
        }
    });

    test("chord modifiers keep reporting themselves as held", () => {
        expect(
            getActiveHotkey(/** @type {any} */ ({ key: "Control", ctrlKey: true })),
        ).toBe("control");
        expect(
            getActiveHotkey(/** @type {any} */ ({ key: "Shift", shiftKey: true })),
        ).toBe("shift");
        expect(getActiveHotkey(/** @type {any} */ ({ key: "Alt", altKey: true }))).toBe(
            "alt",
        );
    });

    test("a real chord over a modifier-held state is unaffected", () => {
        expect(
            getActiveHotkey(
                /** @type {any} */ ({
                    key: "s",
                    code: "KeyS",
                    ctrlKey: true,
                    metaKey: true,
                }),
            ),
        ).toBe("control+s");
    });
});

describe("includesOverlayModifier matches whole tokens, not substrings", () => {
    test("exact modifier token matches; a look-alike substring does not", async () => {
        await makeMockEnv();
        const hotkey = getService("hotkey"); // default overlayModifier is "alt"
        expect(hotkey.includesOverlayModifier("alt+a")).toBe(true);
        expect(hotkey.includesOverlayModifier("control+a")).toBe(false);
        // Regression: the former `hotkey.includes("alt")` matched any token
        // *containing* the modifier name -- "salt" and "alter" both contain
        // "alt". Whole-token matching rejects them.
        expect(hotkey.includesOverlayModifier("salt+a")).toBe(false);
        expect(hotkey.includesOverlayModifier("alter+a")).toBe(false);
    });

    test("compound overlay modifier needs every token present", async () => {
        // `includesOverlayModifier` reads the module-level `hotkeyService.overlayModifier`.
        patchWithCleanup(hotkeyService, { overlayModifier: "control+alt" });
        await makeMockEnv();
        const hotkey = getService("hotkey");
        expect(hotkey.includesOverlayModifier("control+alt+a")).toBe(true);
        expect(hotkey.includesOverlayModifier("alt+a")).toBe(false);
        expect(hotkey.includesOverlayModifier("control+a")).toBe(false);
    });
});
