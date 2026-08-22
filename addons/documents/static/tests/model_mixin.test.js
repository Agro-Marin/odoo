import { DocumentsKanbanModel } from "@documents/views/kanban/documents_kanban_model";
import { describe, expect, test } from "@odoo/hoot";
import { defineModels, onRpc, patchWithCleanup } from "@web/../tests/web_test_helpers";

import { DocumentsModels } from "./helpers/data.js";
import { makeDocumentsMockEnv } from "./helpers/model.js";
import { mountDocumentsKanbanView } from "./helpers/views/kanban.js";

describe.current.tags("desktop");

defineModels(DocumentsModels);

/**
 * @returns {Promise<{contexts: Object[], getModel: () => Object}>}
 */
async function mountWithSearchReadSpy() {
    await makeDocumentsMockEnv();
    const contexts = [];
    onRpc("documents.document", "web_search_read", ({ kwargs }) => {
        contexts.push(kwargs.context || {});
    });
    let model;
    patchWithCleanup(DocumentsKanbanModel.prototype, {
        setup() {
            super.setup(...arguments);
            model = this;
        },
    });
    await mountDocumentsKanbanView();
    return { contexts, getModel: () => model };
}

test("the initial load carries skip_res_field_check", async () => {
    const { contexts } = await mountWithSearchReadSpy();

    expect(contexts.length).toBeGreaterThan(0, {
        message: "the view issued at least one search_read",
    });
    expect(contexts.at(0).skip_res_field_check).toBe(true);
});

test("an argument-less reload still carries skip_res_field_check", async () => {
    const { contexts, getModel } = await mountWithSearchReadSpy();
    const initialCount = contexts.length;

    await getModel().load();

    expect(contexts.length).toBeGreaterThan(initialCount, {
        message: "the bare reload hit the server",
    });
    expect(contexts.at(-1).skip_res_field_check).toBe(true, {
        message: "every documents.document read is flagged, not just the mount one",
    });
});

test("the flag survives a load whose params carry their own context", async () => {
    const { contexts, getModel } = await mountWithSearchReadSpy();

    await getModel().load({ context: { lang: "en_US" } });

    expect(contexts.at(-1).skip_res_field_check).toBe(true);
    expect(contexts.at(-1).lang).toBe("en_US", {
        message: "the caller's own context keys are preserved",
    });
});

test("load() does not write into the object it is given", async () => {
    const { getModel } = await mountWithSearchReadSpy();
    const callerOwned = { context: { some_key: 1 } };

    await getModel().load(callerOwned);

    expect(callerOwned.context).toEqual(
        { some_key: 1 },
        { message: "the caller's context object is left untouched" },
    );
});
