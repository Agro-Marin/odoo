import { describe, expect, test } from "@odoo/hoot";
import {
    defineModels,
    getService,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";

import { DocumentsModels } from "./helpers/data.js";
import { makeDocumentsMockEnv } from "./helpers/model.js";

describe.current.tags("headless");

defineModels(DocumentsModels);

/**
 * @param {string|null} value
 * @returns {Promise<Object>}
 */
async function startWith(value) {
    const store = { documentsChatterVisible: value };
    patchWithCleanup(browser.localStorage, {
        getItem: (key) => (key in store ? store[key] : null),
        setItem: (key, val) => {
            store[key] = String(val);
        },
    });
    await makeDocumentsMockEnv();
    return getService("document.document");
}

test("a well-formed value is honoured", async () => {
    const service = await startWith("true");
    expect(service.rightPanelReactive.visible).toBe(true);
});

test("an explicit false is honoured", async () => {
    const service = await startWith("false");
    expect(service.rightPanelReactive.visible).toBe(false);
});

test("a missing value defaults to hidden", async () => {
    const service = await startWith(null);
    expect(service.rightPanelReactive.visible).toBe(false);
});

test("a corrupt value does not take the service down", async () => {
    const service = await startWith("not json at all");
    expect(service.rightPanelReactive.visible).toBe(false, {
        message: "falls back to hidden instead of throwing out of start()",
    });
});

test("the literal string 'undefined' does not take the service down", async () => {
    const service = await startWith("undefined");
    expect(service.rightPanelReactive.visible).toBe(false);
});
