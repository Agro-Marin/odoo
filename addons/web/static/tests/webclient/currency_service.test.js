// @ts-check

import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-dom";
import {
    defineModels,
    getService,
    makeMockEnv,
    models,
    onRpc,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { rpcBus } from "@web/core/network/rpc";
import { currencies } from "@web/services/currency";

class Currency extends models.Model {
    _name = "res.currency";
    get_all_currencies() {
        return {
            1: { symbol: "$", position: "before", digits: 2 },
        };
    }
}
class Notcurrency extends models.Model {}

defineModels([Currency, Notcurrency]);

test("reload currencies when updating a res.currency", async () => {
    onRpc(({ model, method }) => {
        expect.step([model, method]);
    });
    await makeMockEnv();
    expect.verifySteps([]);
    await getService("orm").read("res.currency", [32]);
    expect.verifySteps([["res.currency", "read"]]);
    await getService("orm").unlink("res.currency", [32]);
    expect.verifySteps([
        ["res.currency", "unlink"],
        ["res.currency", "get_all_currencies"],
    ]);
    await getService("orm").unlink("notcurrency", [32]);
    expect.verifySteps([["notcurrency", "unlink"]]);
    expect(Object.keys(currencies)).toEqual(["1"]);
});

test("do not reload webclient when updating a res.currency, but there is an error", async () => {
    onRpc("get_all_currencies", ({ method }) => {
        expect.step(method);
    });
    await makeMockEnv();
    expect.verifySteps([]);
    rpcBus.trigger("RPC:RESPONSE", {
        data: { params: { model: "res.currency", method: "write" } },
        settings: {},
        result: {},
    });
    await animationFrame();
    expect.verifySteps(["get_all_currencies"]);
    rpcBus.trigger("RPC:RESPONSE", {
        data: { params: { model: "res.currency", method: "write" } },
        settings: {},
        error: {},
    });
    expect.verifySteps([]);
});

test("a failed background currency reload does not raise an unhandled rejection", async () => {
    // The reload is fire-and-forget: a rejected `get_all_currencies` must be
    // swallowed (via console.warn), not left as an unhandled rejection.
    patchWithCleanup(console, {
        warn: () => expect.step("warn"),
    });
    onRpc("get_all_currencies", () => {
        throw new Error("get_all_currencies failed");
    });
    await makeMockEnv();
    rpcBus.trigger("RPC:RESPONSE", {
        data: { params: { model: "res.currency", method: "write" } },
        settings: {},
        result: {},
    });
    await animationFrame();
    // The rejection was routed to console.warn, not left unhandled.
    expect.verifySteps(["warn"]);
});
