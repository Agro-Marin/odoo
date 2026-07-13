/** @odoo-module native */
import { Deferred } from "./bus_worker_utils.js";

export class ElectionWorker {
    MAIN_TAB_TIMEOUT_PERIOD = 3000;

    /** @type {Set<MessagePort>} */
    candidates = new Set();
    /** @type {Deferred|null} */
    electionDeferred = null;
    /** @type {number|null} */
    heartbeatRequestInterval = null;
    lastHeartbeat = Date.now();
    /** @type {Deferred|null} */
    masterReplyDeferred = null;
    /** @type {MessagePort|null} */
    masterTab = null;

    constructor() {
        setInterval(() => {
            if (Date.now() - this.lastHeartbeat > this.MAIN_TAB_TIMEOUT_PERIOD) {
                this.startElection();
            }
        }, this.MAIN_TAB_TIMEOUT_PERIOD);
    }

    requestHeartbeat(messagePort) {
        if (messagePort) {
            messagePort.postMessage({ type: "ELECTION:HEARTBEAT_REQUEST" });
            return;
        }
        for (const candidate of this.candidates) {
            candidate.postMessage({ type: "ELECTION:HEARTBEAT_REQUEST" });
        }
    }

    async ensureMasterPresence() {
        this.masterReplyDeferred ??= new Deferred();
        if (this.masterTab) {
            this.requestHeartbeat(this.masterTab);
        } else {
            this.startElection();
        }
        await this.masterReplyDeferred;
    }

    startElection() {
        clearInterval(this.heartbeatRequestInterval);
        this.masterTab?.postMessage({ type: "ELECTION:UNASSIGN_MASTER" });
        this.masterTab = null;
        this.electionDeferred ??= new Deferred();
        this.requestHeartbeat();
    }

    /**
     * Drop a candidate whose port was found dead by the websocket worker's
     * liveness sweep (it cannot send ELECTION:UNREGISTER itself). Re-elect
     * if it was the master.
     *
     * @param {MessagePort} messagePort
     */
    evictCandidate(messagePort) {
        this.candidates.delete(messagePort);
        if (this.masterTab === messagePort) {
            this.startElection();
        }
    }

    finishElection(messagePort) {
        this.masterTab = messagePort;
        messagePort.postMessage({ type: "ELECTION:ASSIGN_MASTER" });
        this.electionDeferred.resolve();
        this.electionDeferred = null;
        this.heartbeatRequestInterval = setInterval(
            () => this.requestHeartbeat(this.masterTab),
            this.MAIN_TAB_TIMEOUT_PERIOD / 2,
        );
    }

    async handleMessage(event) {
        const { action } = event.data;
        if (!action?.startsWith("ELECTION:")) {
            return;
        }
        switch (action) {
            case "ELECTION:REGISTER":
                this.candidates.add(event.target);
                if (!this.masterTab) {
                    if (this.electionDeferred) {
                        // An election is already in progress: poll the newcomer
                        // directly so it can win it. Previously this awaited
                        // ``electionDeferred``, which — if that election had
                        // stalled with no candidates — blocked the new tab for
                        // up to ``MAIN_TAB_TIMEOUT_PERIOD`` until the periodic
                        // staleness check re-broadcast heartbeat requests.
                        this.requestHeartbeat(event.target);
                    } else {
                        this.startElection();
                    }
                }
                break;
            case "ELECTION:UNREGISTER":
                this.candidates.delete(event.target);
                if (this.masterTab === event.target) {
                    this.startElection();
                }
                break;
            case "ELECTION:IS_MASTER?":
                await this.ensureMasterPresence();
                event.target.postMessage({
                    type: "ELECTION:IS_MASTER_RESPONSE",
                    data: { answer: this.masterTab === event.target },
                });
                break;
            case "ELECTION:HEARTBEAT":
                if (this.electionDeferred && this.candidates.has(event.target)) {
                    // Only a registered candidate may win: a stale heartbeat
                    // reply from a tab that unregistered while the request was
                    // in flight would otherwise be crowned master — a master
                    // that denies it client-side (its state is UNREGISTERED),
                    // freezing the cluster with no acting main tab.
                    this.finishElection(event.target);
                }
                if (this.masterTab === event.target) {
                    this.lastHeartbeat = Date.now();
                    this.masterReplyDeferred?.resolve();
                    this.masterReplyDeferred = null;
                }
                break;
            default:
                console.warn("Unknown message action:", action);
        }
    }
}
