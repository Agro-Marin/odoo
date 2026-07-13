/** @odoo-module native */
/* eslint-disable no-restricted-globals */

import { BaseWorker } from "./base_worker.js";
import { WebsocketWorker } from "./websocket_worker.js";

(function () {
    // Single source of truth for the shared-vs-dedicated distinction (the
    // worker kind is encoded in the name by `worker_service.startWorker`):
    // derived once here and passed explicitly to whoever needs it.
    const isShared = self.name.includes("shared");
    const baseWorker = new BaseWorker(self.name, isShared);
    const websocketWorker = new WebsocketWorker(self.name);
    // Main-tab election no longer lives in the worker: it is done in the page
    // via the Web Locks API (see multi_tab_service.js), so the worker only
    // relays bus notifications and handles the base-worker init handshake.

    if (isShared) {
        // The script is running in a shared worker.
        self.onconnect = (ev) => {
            const client = ev.ports[0];
            // Register the base worker to handle first init message.
            client.addEventListener("message", (ev) => baseWorker.handleMessage(ev));
            // let's register every tab connection to the worker in order to relay
            // notifications coming from the websocket.
            websocketWorker.registerClient(client);
            client.start();
        };
    } else {
        // The script is running in a simple web worker (SharedWorker missing
        // or its construction failed — see worker_service `onInitError`).
        self.addEventListener("message", (ev) => baseWorker.handleMessage(ev));
        websocketWorker.registerClient(self);
    }
})();
