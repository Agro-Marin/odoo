import { getWebSocketWorker } from "@bus/../tests/mock_websocket";
import { ElectionWorker } from "@bus/workers/election_worker";
import { mockWorker } from "@odoo/hoot-mock";
import { MockServer } from "@web/../tests/web_test_helpers";
import { patch } from "@web/core/utils/patch";

let electionWorker = null;

export function getElectionWorker() {
    return electionWorker;
}

/**
 * @param {SharedWorker | Worker} worker
 */
function onWorkerConnected(worker) {
    const client = worker._messageChannel.port2;
    client.addEventListener("message", (ev) => {
        electionWorker.handleMessage(ev);
    });
    client.start();
    // Compose the two workers exactly like bus_worker_script.js:16: a client
    // found dead by the websocket worker's liveness sweep must also leave the
    // election (and trigger re-election if it was master). Both workers share
    // the same `port2` client object, so the evicted client matches the
    // registered candidate.
    const websocketWorker = getWebSocketWorker();
    if (websocketWorker) {
        websocketWorker.onClientEvicted = (evicted) =>
            electionWorker.evictCandidate(evicted);
    }
}

function setupElectionWorker() {
    electionWorker = new ElectionWorker();
    mockWorker(onWorkerConnected);
}

patch(MockServer.prototype, {
    start() {
        setupElectionWorker();
        return super.start(...arguments);
    },
});
