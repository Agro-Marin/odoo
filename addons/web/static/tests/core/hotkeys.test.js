// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { getActiveHotkey } from "@web/core/browser/hotkeys";

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
