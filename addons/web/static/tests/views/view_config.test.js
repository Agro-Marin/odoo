// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { extractLayoutComponents } from "@web/search/layout";
import { getDefaultConfig } from "@web/views/view";
import {
    VIEW_CONFIG_FOREIGN_SURFACE,
    VIEW_CONFIG_SURFACE,
} from "@web/views/view_config";

describe.current.tags("headless");

test("every key getDefaultConfig seeds is declared", () => {
    const undeclared = Object.keys(getDefaultConfig()).filter(
        (key) => !VIEW_CONFIG_SURFACE.includes(key),
    );
    expect(undeclared).toEqual([], {
        message: "getDefaultConfig seeds a key VIEW_CONFIG_SURFACE does not name",
    });
});

test("every key extractLayoutComponents injects is declared", () => {
    const undeclared = Object.keys(extractLayoutComponents({})).filter(
        (key) => !VIEW_CONFIG_SURFACE.includes(key),
    );
    expect(undeclared).toEqual([]);
});

test("the declared surface has no duplicates and is sorted within its groups", () => {
    expect(VIEW_CONFIG_SURFACE.length).toBe(new Set(VIEW_CONFIG_SURFACE).size);
    expect(VIEW_CONFIG_FOREIGN_SURFACE.length).toBe(
        new Set(VIEW_CONFIG_FOREIGN_SURFACE).size,
    );
});

test("owned and foreign surfaces are disjoint", () => {
    const owned = new Set(VIEW_CONFIG_SURFACE);
    const overlap = VIEW_CONFIG_FOREIGN_SURFACE.filter((key) => owned.has(key));
    expect(overlap).toEqual([], {
        message:
            "a key cannot be both web's contract and a foreign squatter — " +
            "promote it into VIEW_CONFIG_SURFACE and drop it from the foreign list, " +
            "or the distinction the two lists exist to draw has collapsed",
    });
});

test("the declared surface is not empty", () => {
    expect(VIEW_CONFIG_SURFACE.length).toBeGreaterThan(20);
});
