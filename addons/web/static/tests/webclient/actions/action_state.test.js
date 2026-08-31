// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { makeMockEnv, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { getActionParams } from "@web/webclient/actions/action_state";

describe.current.tags("desktop");

function seedLastAction(action) {
    browser.sessionStorage.setItem("current_action", JSON.stringify(action));
}

test("an action-based state restores the serialized search model", async () => {
    await makeMockEnv();
    const params = getActionParams({
        action: 3,
        globalState: { searchModel: '{"nextId":1}' },
    });
    expect(params.options.props.globalState).toEqual({ searchModel: '{"nextId":1}' });
});

test("a model-based list state restores the serialized search model too", async () => {
    await makeMockEnv();
    seedLastAction({ res_model: "partner" });
    const params = getActionParams({
        model: "partner",
        view_type: "list",
        globalState: { searchModel: '{"nextId":1}' },
    });
    expect(params.options.viewType).toBe("list");
    expect(params.options.props?.globalState).toEqual({ searchModel: '{"nextId":1}' });
});

test("a synthesised record action carries the id on the request, the search model on the props", async () => {
    await makeMockEnv();
    seedLastAction({});
    const params = getActionParams({
        model: "partner",
        resId: 7,
        globalState: { searchModel: '{"nextId":1}' },
    });
    expect(params.actionRequest.res_id).toBe(7);
    expect(params.actionRequest.res_model).toBe("partner");
    expect(params.options.props.globalState).toEqual({ searchModel: '{"nextId":1}' });
});

test("a cached model action restores the record through the props", async () => {
    await makeMockEnv();
    seedLastAction({ res_model: "partner", views: [[false, "form"]] });
    const params = getActionParams({ model: "partner", resId: 7 });
    expect(params.options.props.resId).toBe(7);
    expect(params.options.viewType).toBe("form");
});

test("a new record carries no resId", async () => {
    await makeMockEnv();
    seedLastAction({});
    const params = getActionParams({ model: "partner", resId: "new" });
    expect(params.options.props?.resId).toBe(undefined);
    expect(params.actionRequest.res_model).toBe("partner");
});

test("popping an unresolvable leaf reports how many entries it dropped", async () => {
    await makeMockEnv();
    seedLastAction({});
    const params = getActionParams({
        model: "unresolvable",
        actionStack: [{ action: 3, view_type: "list" }, { model: "unresolvable" }],
    });
    expect(params.actionRequest).toBe(3);
    expect(params.options.poppedLeaves).toBe(1);
});

test("each further pop increments the count", async () => {
    await makeMockEnv();
    seedLastAction({});
    const params = getActionParams({
        model: "unresolvable",
        actionStack: [
            { action: 3, view_type: "list" },
            { model: "unresolvable" },
            { model: "unresolvable" },
        ],
    });
    expect(params.actionRequest).toBe(3);
    expect(params.options.poppedLeaves).toBe(2);
});

test("a deep action stack reads the stored action once, not once per level", async () => {
    // getActionParams recurses one level per leaf it cannot resolve. Re-reading
    // and re-parsing the same sessionStorage blob at every level is work that
    // grows with breadcrumb depth for no gain.
    let reads = 0;
    patchWithCleanup(browser.sessionStorage, {
        getItem(key) {
            if (key === "current_action") {
                reads++;
            }
            return super.getItem(key);
        },
    });

    const actionStack = [
        { action: "unresolvable-1" },
        { action: "unresolvable-2" },
        { action: "unresolvable-3" },
        { model: "no.such.model", view_type: "list" },
    ];
    getActionParams({ ...actionStack.at(-1), actionStack });

    expect(reads).toBe(1);
});
