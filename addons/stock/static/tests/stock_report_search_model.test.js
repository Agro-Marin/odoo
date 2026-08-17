// @ts-check

import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { StockReportSearchModel } from "@stock/views/search/stock_report_search_model";
import {
    defineModels,
    fields,
    makeMockEnv,
    models,
    onRpc,
} from "@web/../tests/web_test_helpers";

describe.current.tags("headless");

class StockWarehouse extends models.Model {
    _name = "stock.warehouse";

    name = fields.Char();
    code = fields.Char();

    _records = [
        { id: 1, name: "Almacen Central", code: "CDG" },
        { id: 2, name: "Almacen Norte", code: "NTE" },
    ];
}

defineModels([StockWarehouse]);

let env;

beforeEach(async () => {
    env = await makeMockEnv();
});

function makeSearchModel(context = {}) {
    const model = new StockReportSearchModel(env, { orm: env.services.orm });
    // `context` is a getter memoised on `_context`, normally filled by load().
    model._context = context;
    return model;
}

test("get_current_warehouses is called with no record ids", async () => {
    /** @type {any} */
    let received;
    onRpc("stock.warehouse", "get_current_warehouses", ({ args }) => {
        received = args;
        return [];
    });

    await makeSearchModel()._loadWarehouses();

    expect(received).toEqual([], {
        message:
            "get_current_warehouses is @api.model, so call_kw does not strip a leading" +
            " ids argument: passing one reaches the method as an extra positional",
    });
});

test("the warehouses the server returns reach the search panel", async () => {
    onRpc("stock.warehouse", "get_current_warehouses", () => [
        { id: 1, name: "Almacen Central", code: "CDG" },
        { id: 2, name: "Almacen Norte", code: "NTE" },
    ]);

    const model = makeSearchModel();
    await model._loadWarehouses();

    expect(model.getWarehouses()).toHaveLength(2);
});

test("a failing call leaves the panel empty instead of breaking the view", async () => {
    onRpc("stock.warehouse", "get_current_warehouses", () => {
        throw new Error("boom");
    });

    const model = makeSearchModel();
    await model._loadWarehouses();

    expect(model.getWarehouses()).toEqual([]);
});
