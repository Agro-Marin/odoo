import { DocumentsKanbanModel } from "@documents/views/kanban/documents_kanban_model";
import { describe, expect, test } from "@odoo/hoot";
import { defineModels, onRpc, patchWithCleanup } from "@web/../tests/web_test_helpers";

import { DocumentsModels } from "./helpers/data.js";
import { makeDocumentsMockEnv } from "./helpers/model.js";
import { mountDocumentsKanbanView } from "./helpers/views/kanban.js";

/**
 * `DocumentsModelMixin.load` regression tests.
 *
 * On `skip_res_field_check` itself: it was measured against a real database and
 * is INERT for this model. Every `ir.attachment._search` a documents read
 * triggers is an `[('id','in',[...])]` batch, and `ir_attachment._search`
 * already exempts any domain mentioning `id` from the `res_field` narrowing;
 * related `attachment_id.*` fields resolve to a LEFT JOIN, never a nested
 * `_search`. Setting or omitting it returns identical records. These tests
 * therefore assert *plumbing*, not data correctness.
 *
 * The mixin used to install that flag with
 * `for (const arg of arguments) { arg.context["skip_res_field_check"] = true }`.
 * That did reach the server, but only as a side effect: the one caller that
 * passes anything is `useModel`'s `load(getSearchParams(props))`, whose
 * `params.context` *is* the controller's `props.context` object. The loop
 * stamped that object in place, `computeNextConfig` copied the stamped context
 * into `this.config`, and every later argument-less `load()` inherited it from
 * there.
 *
 * Only the last test fails against the old implementation; the others pass both
 * ways and are here to characterise what must keep holding. The defect being
 * fixed is exactly one thing: `load()` writing into an object it does not own.
 */
describe.current.tags("desktop");

defineModels(DocumentsModels);

/**
 * Mount a documents kanban and expose both the model instance and the context
 * of every `web_search_read` it issues.
 *
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

    // The exact reload shape `_notifyChange` uses.
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

    // A caller-built params object, as `useModel` produces on every search
    // change. The flag has to be re-applied on top of it rather than assumed to
    // already be in `this.config` from an earlier stamped load.
    await getModel().load({ context: { lang: "en_US" } });

    expect(contexts.at(-1).skip_res_field_check).toBe(true);
    expect(contexts.at(-1).lang).toBe("en_US", {
        message: "the caller's own context keys are preserved",
    });
});

test("load() does not write into the object it is given", async () => {
    const { getModel } = await mountWithSearchReadSpy();
    // Stand-in for `component.props`, which is what the upload handler used to
    // hand to `load()` -- and which the mixin then permanently stamped.
    const callerOwned = { context: { some_key: 1 } };

    await getModel().load(callerOwned);

    expect(callerOwned.context).toEqual(
        { some_key: 1 },
        { message: "the caller's context object is left untouched" },
    );
});
