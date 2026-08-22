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
import { currencies } from "@web/core/currency";
import { rpcBus, RPCError } from "@web/core/network/rpc";

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

test("do not reload webclient when the res.currency write was refused", async () => {
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
    const refused = new RPCError("Access denied");
    refused.exceptionName = "odoo.exceptions.AccessError";
    rpcBus.trigger("RPC:RESPONSE", {
        data: { params: { model: "res.currency", method: "write" } },
        settings: {},
        error: refused,
    });
    await animationFrame();
    expect.verifySteps([]);
});

test("a failed background currency reload does not raise an unhandled rejection", async () => {
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
    expect.verifySteps(["warn"]);
});

test("destroy() releases the res.currency subscription", async () => {
    onRpc("get_all_currencies", ({ method }) => {
        expect.step(method);
    });
    const env = await makeMockEnv();
    const fireWrite = () =>
        rpcBus.trigger("RPC:RESPONSE", {
            data: { params: { model: "res.currency", method: "write" } },
            settings: {},
            result: {},
        });

    fireWrite();
    await animationFrame();
    expect.verifySteps(["get_all_currencies"]);

    getService("currency").destroy();
    fireWrite();
    await animationFrame();
    expect.verifySteps([]);

    env.destroy();
});

test("env.destroy() reaches the currency service", async () => {
    onRpc("get_all_currencies", ({ method }) => {
        expect.step(method);
    });
    const env = await makeMockEnv();
    env.destroy();
    rpcBus.trigger("RPC:RESPONSE", {
        data: { params: { model: "res.currency", method: "write" } },
        settings: {},
        result: {},
    });
    await animationFrame();
    expect.verifySteps([]);
});
