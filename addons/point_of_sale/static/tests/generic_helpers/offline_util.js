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
        // before any request. This is the cleanest primitive: it doesn't
        // depend on the transport internals. `window.posmodel` is a plain
        // global (see pos_app.js), so it is the same store instance.
        window.posmodel.data.network.offline = true;
        // Belt-and-suspenders for any path that reaches the transport anyway.
        // `browser.fetch` (which rpc() uses) IS now patchable from a test: the
        // ESM singleton split that used to give the test bundle its own copy of
        // `@web/core/browser/browser` is fixed — secondary bundles alias shared
        // core specifiers to `odoo.loader.modules` shims (see esm_bridges /
        // ir_qweb_assets `_secondary_parent_stubs`). Note `window.fetch` still
        // has no effect on rpc: browser.js captures `window.fetch.bind(window)`
        // at import, so reassigning `window.fetch` doesn't reach that capture —
        // which is exactly why we patch `browser.fetch`, not `window.fetch`.
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
