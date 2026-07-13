import { ElectionWorker } from "@bus/workers/election_worker";
import { describe, expect, test } from "@odoo/hoot";

describe.current.tags("headless");

/** A stand-in for a client MessagePort. */
const makePort = () => ({ postMessage() {} });

/**
 * Drive a message into the worker as if it came from `port`. The REGISTER /
 * UNREGISTER / HEARTBEAT paths run synchronously (no await before their logic).
 */
const send = (worker, port, action) =>
    worker.handleMessage({ data: { action }, target: port });

test("a candidate that replies to the heartbeat request wins the election", () => {
    const worker = new ElectionWorker();
    const p1 = makePort();
    send(worker, p1, "ELECTION:REGISTER");
    // Registering the first candidate starts an election that polls it.
    send(worker, p1, "ELECTION:HEARTBEAT");
    expect(worker.masterTab).toBe(p1);
});

test("evictCandidate re-elects when the evicted candidate was the master", () => {
    const worker = new ElectionWorker();
    const p1 = makePort();
    const p2 = makePort();
    send(worker, p1, "ELECTION:REGISTER");
    send(worker, p1, "ELECTION:HEARTBEAT");
    expect(worker.masterTab).toBe(p1);
    send(worker, p2, "ELECTION:REGISTER");
    // The master's port is found dead by the liveness sweep -> evicted.
    worker.evictCandidate(p1);
    expect(worker.candidates.has(p1)).toBe(false);
    expect(worker.masterTab).toBe(null);
    // The surviving candidate can now win the fresh election.
    send(worker, p2, "ELECTION:HEARTBEAT");
    expect(worker.masterTab).toBe(p2);
});

test("evicting a non-master candidate does not disturb the master", () => {
    const worker = new ElectionWorker();
    const master = makePort();
    const other = makePort();
    send(worker, master, "ELECTION:REGISTER");
    send(worker, master, "ELECTION:HEARTBEAT");
    send(worker, other, "ELECTION:REGISTER");
    worker.evictCandidate(other);
    expect(worker.masterTab).toBe(master);
    expect(worker.candidates.has(other)).toBe(false);
});

test("a stale heartbeat from an unregistered tab cannot win the election", () => {
    const worker = new ElectionWorker();
    const p1 = makePort();
    send(worker, p1, "ELECTION:REGISTER");
    // The tab unregisters while its heartbeat reply is still in flight.
    send(worker, p1, "ELECTION:UNREGISTER");
    // The stale heartbeat must NOT crown a tab that is no longer a candidate
    // (it would deny mastership client-side and freeze the cluster).
    send(worker, p1, "ELECTION:HEARTBEAT");
    expect(worker.masterTab).toBe(null);
});
