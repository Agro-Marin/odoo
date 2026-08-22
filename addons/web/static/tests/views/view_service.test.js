// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    defineModels,
    getService,
    makeMockEnv,
    models,
    onRpc,
} from "@web/../tests/web_test_helpers";

describe.current.tags("headless");

class TakeFive extends models.Model {
    _name = "take.five";
    _views = {
        "list,99": `<list><field name="display_name" /></list>`,
    };
}

class IrUiView extends models.Model {
    _name = "ir.ui.view";
}

defineModels([TakeFive, IrUiView]);

test("stores calls in cache in success", async () => {
    expect.assertions(1);
    onRpc("get_views", () => {
        expect.step("get_views");
    });
    await makeMockEnv();
    await getService("view").loadViews(
        {
            resModel: "take.five",
            views: [[99, "list"]],
            context: { default_field_value: 1 },
        },
        {},
    );
    await getService("view").loadViews(
        {
            resModel: "take.five",
            views: [[99, "list"]],
            context: { default_field_value: 2 },
        },
        {},
    );
    expect.verifySteps(["get_views"]);
});

test("stores calls in cache when failed", async () => {
    expect.assertions(3);
    onRpc("get_views", () => {
        expect.step("get_views");
        throw new Error("my little error");
    });
    await makeMockEnv();
    await expect(
        getService("view").loadViews(
            {
                resModel: "take.five",
                views: [[99, "list"]],
            },
            {},
        ),
    ).rejects.toThrow(/my little error/);
    await expect(
        getService("view").loadViews(
            {
                resModel: "take.five",
                views: [[99, "list"]],
            },
            {},
        ),
    ).rejects.toThrow(/my little error/);
    expect.verifySteps(["get_views", "get_views"]);
});

test("clear cache when updating ir.ui.view", async () => {
    expect.assertions(4);
    onRpc("get_views", () => {
        expect.step("get_views");
    });
    await makeMockEnv();
    const loadView = () =>
        getService("view").loadViews(
            {
                resModel: "take.five",
                views: [[99, "list"]],
                context: { default_field_value: 1 },
            },
            {},
        );
    await loadView();
    expect.verifySteps(["get_views"]);
    await loadView();
    expect.verifySteps([]);
    await getService("orm").unlink("ir.ui.view", [3]);
    await loadView();
    expect.verifySteps(["get_views"]);
    await getService("orm").unlink("take.five", [3]);
    await loadView();
    expect.verifySteps([]);
});

test("clear cache when creating an ir.filters favorite (create_filter)", async () => {
    onRpc("get_views", () => {
        expect.step("get_views");
    });
    onRpc("create_filter", () => [7]);
    await makeMockEnv();
    const loadView = () =>
        getService("view").loadViews(
            { resModel: "take.five", views: [[99, "list"]], context: {} },
            {},
        );
    await loadView();
    expect.verifySteps(["get_views"]);
    await loadView();
    expect.verifySteps([]);
    await getService("orm").call("ir.filters", "create_filter", [{ name: "F" }]);
    await loadView();
    expect.verifySteps(["get_views"]);
});
