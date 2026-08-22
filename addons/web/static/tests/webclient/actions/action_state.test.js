// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { makeMockEnv } from "@web/../tests/web_test_helpers";
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
