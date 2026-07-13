/** @odoo-module native */
/* eslint-env worker */
/* eslint-disable no-restricted-globals */

import { BaseWorker } from "./base_worker.js";
import { ElectionWorker } from "./election_worker.js";
import { WebsocketWorker } from "./websocket_worker.js";

(function () {
    const baseWorker = new BaseWorker(self.name);
    const websocketWorker = new WebsocketWorker(self.name);
    const electionWorker = new ElectionWorker();
    // A dead port found by the liveness sweep must leave the election too:
    // it cannot send ELECTION:UNREGISTER itself, and a dead master would
    // otherwise block re-election until its heartbeat times out.
    websocketWorker.onClientEvicted = (client) => electionWorker.evictCandidate(client);

    if (self.name.includes("shared")) {
        // The script is running in a shared worker.
        onconnect = (ev) => {
            const client = ev.ports[0];
            // Register the base worker to handle first init message.
            // Register the current client for main tab election.
            client.addEventListener("message", (ev) => {
                baseWorker.handleMessage(ev);
                electionWorker.handleMessage(ev);
            });
            // let's register every tab connection to the worker in order to relay
            // notifications coming from the websocket.
            websocketWorker.registerClient(client);
            client.start();
        };
    } else {
        // The script is running in a simple web worker (SharedWorker missing
        // or its construction failed — see worker_service `onInitError`).
        // The election handler MUST be wired here too: multi_tab picks the
        // election-based service on `SharedWorker` *presence*, so after a
        // runtime fallback the tab still sends ELECTION:* messages. Without a
        // handler, `ELECTION:IS_MASTER?` is never answered and every
        // `multiTab.isOnMainTab()` await hangs forever. With one worker per
        // tab, each tab simply elects itself — the correct degenerate case.
        self.addEventListener("message", (ev) => {
            baseWorker.handleMessage(ev);
            electionWorker.handleMessage(ev);
        });
        websocketWorker.registerClient(self);
    }
})();
