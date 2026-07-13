// @ts-check

import { beforeEach, expect, test } from "@odoo/hoot";
import { advanceTime, animationFrame, runAllTimers } from "@odoo/hoot-mock";
import {
    getService,
    mountWithCleanup,
    patchWithCleanup,
    serverState,
} from "@web/../tests/web_test_helpers";
import { config as transitionConfig } from "@web/components/transition";
import { rpcBus } from "@web/core/network/rpc";
import { LoadingIndicator } from "@web/webclient/loading_indicator/loading_indicator";

const payload = (id) => ({
    data: { id, params: { model: "", method: "" } },
    settings: {},
});

beforeEach(() => {
    patchWithCleanup(transitionConfig, { disabled: true });
});

test("displays the loading indicator in non debug mode", async () => {
    await mountWithCleanup(LoadingIndicator, { noMainContainer: true });
    expect(".o_loading_indicator").toHaveCount(0, {
        message: "the loading indicator should not be displayed",
    });
    rpcBus.trigger("RPC:REQUEST", payload(1));
    await runAllTimers();
    await animationFrame();
    expect(".o_loading_indicator").toHaveCount(1, {
        message: "the loading indicator should be displayed",
    });
    expect(".o_loading_indicator").toHaveText("Loading", {
        message: "the loading indicator should display 'Loading'",
    });
    rpcBus.trigger("RPC:RESPONSE", payload(1));
    await runAllTimers();
    await animationFrame();
    expect(".o_loading_indicator").toHaveCount(0, {
        message: "the loading indicator should not be displayed",
    });
});

test("displays the loading indicator for one rpc in debug mode", async () => {
    serverState.debug = "1";
    await mountWithCleanup(LoadingIndicator, { noMainContainer: true });
    expect(".o_loading_indicator").toHaveCount(0, {
        message: "the loading indicator should not be displayed",
    });
    rpcBus.trigger("RPC:REQUEST", payload(1));
    await runAllTimers();
    await animationFrame();
    expect(".o_loading_indicator").toHaveCount(1, {
        message: "the loading indicator should be displayed",
    });
    expect(".o_loading_indicator").toHaveText("Loading (1)", {
        message: "the loading indicator should indicate 1 request in progress",
    });
    rpcBus.trigger("RPC:RESPONSE", payload(1));
    await runAllTimers();
    await animationFrame();
    expect(".o_loading_indicator").toHaveCount(0, {
        message: "the loading indicator should not be displayed",
    });
});

test("displays the loading indicator for multi rpc in debug mode", async () => {
    serverState.debug = "1";
    await mountWithCleanup(LoadingIndicator, { noMainContainer: true });
    expect(".o_loading_indicator").toHaveCount(0, {
        message: "the loading indicator should not be displayed",
    });
    rpcBus.trigger("RPC:REQUEST", payload(1));
    rpcBus.trigger("RPC:REQUEST", payload(2));
    await runAllTimers();
    await animationFrame();
    expect(".o_loading_indicator").toHaveCount(1, {
        message: "the loading indicator should be displayed",
    });
    expect(".o_loading_indicator").toHaveText("Loading (2)", {
        message: "the loading indicator should indicate 2 requests in progress.",
    });
    rpcBus.trigger("RPC:REQUEST", payload(3));
    await runAllTimers();
    await animationFrame();
    expect(".o_loading_indicator").toHaveText("Loading (3)", {
        message: "the loading indicator should indicate 3 requests in progress.",
    });
    rpcBus.trigger("RPC:RESPONSE", payload(1));
    await runAllTimers();
    await animationFrame();
    expect(".o_loading_indicator").toHaveText("Loading (2)", {
        message: "the loading indicator should indicate 2 requests in progress.",
    });
    rpcBus.trigger("RPC:REQUEST", payload(4));
    await runAllTimers();
    await animationFrame();
    expect(".o_loading_indicator").toHaveText("Loading (3)", {
        message: "the loading indicator should indicate 3 requests in progress.",
    });
    rpcBus.trigger("RPC:RESPONSE", payload(2));
    rpcBus.trigger("RPC:RESPONSE", payload(3));
    await runAllTimers();
    await animationFrame();
    expect(".o_loading_indicator").toHaveText("Loading (1)", {
        message: "the loading indicator should indicate 1 request in progress.",
    });
    rpcBus.trigger("RPC:RESPONSE", payload(4));
    await runAllTimers();
    await animationFrame();
    expect(".o_loading_indicator").toHaveCount(0, {
        message: "the loading indicator should not be displayed",
    });
});

test("malformed rpcBus events are ignored, not thrown", async () => {
    // A synthetic/malformed event on the shared rpcBus must not throw inside the
    // bus dispatch (the pre-fix code read `detail.settings.silent`, which threw
    // on a missing `settings`), matching the sibling listeners on the same bus.
    await mountWithCleanup(LoadingIndicator, { noMainContainer: true });
    // Guard-ignored shapes: null detail and a missing `data` are dropped outright.
    rpcBus.trigger("RPC:REQUEST", null);
    rpcBus.trigger("RPC:RESPONSE", { settings: {} }); // no data
    // A missing `settings` must not throw. It IS a valid (non-silent) request,
    // so it would legitimately show the indicator — pair it with its response so
    // the tracked count returns to 0 and the indicator stays hidden.
    rpcBus.trigger("RPC:REQUEST", { data: { id: 1 } }); // no settings
    rpcBus.trigger("RPC:RESPONSE", { data: { id: 1 } });
    await runAllTimers();
    await animationFrame();
    expect(".o_loading_indicator").toHaveCount(0, {
        message: "malformed/balanced events should not display the loading indicator",
    });
});

test("loading indicator is not displayed immediately", async () => {
    await mountWithCleanup(LoadingIndicator, { noMainContainer: true });
    const ui = getService("ui");
    ui.bus.addEventListener("BLOCK", () => {
        expect.step("block");
    });
    ui.bus.addEventListener("UNBLOCK", () => {
        expect.step("unblock");
    });
    rpcBus.trigger("RPC:REQUEST", payload(1));
    await animationFrame();
    expect(".o_loading_indicator").toHaveCount(0);
    await advanceTime(400);
    expect(".o_loading_indicator").toHaveCount(1);
    rpcBus.trigger("RPC:RESPONSE", payload(1));
    await animationFrame();
    expect(".o_loading_indicator").toHaveCount(0);
});
