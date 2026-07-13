import { after, describe, test } from "@odoo/hoot";
import { on, runAllTimers, waitFor } from "@odoo/hoot-dom";
import {
    asyncStep,
    contains,
    getService,
    MockServer,
    mountWithCleanup,
    waitForSteps,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { WebClient } from "@web/webclient/webclient";

import { defineBusModels } from "./bus_test_helpers.js";

defineBusModels();
describe.current.tags("desktop");

test("can listen on bus and display notifications in DOM", async () => {
    // Use hoot's `on` (auto-removed via `after`) so this listener on the shared
    // `browser.location` mock does not leak into later suites, where a stray
    // "reload-page" step would corrupt their `waitForSteps` assertions.
    after(on(browser.location, "reload", () => asyncStep("reload-page")));
    await mountWithCleanup(WebClient);
    getService("bus_service").subscribe("bundle_changed", () =>
        asyncStep("bundle_changed"),
    );
    MockServer.env["bus.bus"]._sendone("broadcast", "bundle_changed", {
        server_version: "NEW_MAJOR_VERSION",
    });
    await waitForSteps(["bundle_changed"]);
    await runAllTimers();
    await waitFor(".o_notification", {
        contains: "The page appears to be out of date.",
    });
    await contains(".o_notification button:contains(Refresh)").click();
    await waitForSteps(["reload-page"]);
});
