import { run } from "@point_of_sale/../tests/generic_helpers/utils";
import { browser } from "@web/core/browser/browser";
import { ConnectionLostError } from "@web/core/network/rpc";

const originalBrowserFetch = browser.fetch;
const originalWindowFetch = window.fetch;
const originalSend = XMLHttpRequest.prototype.send;
const originalConsoleError = console.error;

export function setOfflineMode() {
    return run(() => {
        // Simulate offline at the state layer the app actually checks —
        // `pos.data.network.offline`, read by syncAllOrders (and data.call)
        // before any request. The transport itself cannot be intercepted from a
        // test: rpc() goes through `browser.fetch`, which both captured the
        // original window.fetch (bound) at import AND lives in a `browser` module
        // duplicated across the test vs prod ESM bundle — so neither a
        // window.fetch nor a browser.fetch patch here reaches it. `window.posmodel`
        // is a plain global (see pos_app.js), so it is the same store instance.
        window.posmodel.data.network.offline = true;
        // Belt-and-suspenders for any code path that still uses window/XHR directly.
        const throwOffline = () => {
            throw new ConnectionLostError();
        };
        browser.fetch = throwOffline;
        window.fetch = throwOffline;
        XMLHttpRequest.prototype.send = () => {
            throw new ConnectionLostError();
        };
        console.error = (...args) => {
            const message = args[0] instanceof Error ? args[0].message : args[0];
            if (typeof message === "string" && message.includes("ConnectionLostError")) {
                console.info("Connection lost error handled in offline mode:", ...args);
            } else {
                originalConsoleError.apply(console, args);
            }
        };
    }, "Offline mode is now enabled");
}

export function setOnlineMode() {
    return run(() => {
        window.posmodel.data.network.offline = false;
        browser.fetch = originalBrowserFetch;
        window.fetch = originalWindowFetch;
        XMLHttpRequest.prototype.send = originalSend;
        console.error = originalConsoleError;
    }, "Offline mode is now disabled");
}
