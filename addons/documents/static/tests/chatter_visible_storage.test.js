import { describe, expect, test } from "@odoo/hoot";
import {
    defineModels,
    getService,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";

import { DocumentsModels } from "./helpers/data.js";
import { makeDocumentsMockEnv } from "./helpers/model.js";

/**
 * `documentsChatterVisible` is read during `DocumentService.start()`, which the
 * service registry awaits. A raw `JSON.parse` of a corrupt value threw there and
 * took the whole `document.document` service down with it -- verified against a
 * running instance, where the Documents app then refused to load at all and
 * stayed that way until local storage was cleared by hand.
 *
 * The same guard already existed in `documents_search_model._ensureCategoryValue`
 * for `searchpanel_documents_document`; this key was missed.
 */
describe.current.tags("headless");

defineModels(DocumentsModels);

/**
 * Boot the service with `documentsChatterVisible` preset to `value`.
 * @param {string|null} value raw local-storage content
 * @returns {Promise<Object>} the started service
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
    // The exact shape that stopped the app from loading.
    const service = await startWith("not json at all");
    expect(service.rightPanelReactive.visible).toBe(false, {
        message: "falls back to hidden instead of throwing out of start()",
    });
});

test("the literal string 'undefined' does not take the service down", async () => {
    const service = await startWith("undefined");
    expect(service.rightPanelReactive.visible).toBe(false);
});
