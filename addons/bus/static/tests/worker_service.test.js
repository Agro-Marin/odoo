import { defineBusModels } from "@bus/../tests/bus_test_helpers";
import { WORKER_STATE, WorkerService } from "@bus/services/worker_service";
import { describe, expect, test } from "@odoo/hoot";
import { runAllTimers } from "@odoo/hoot-dom";
import {
    getService,
    makeMockEnv,
    makeMockServer,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";

defineBusModels();
describe.current.tags("desktop");

test("J6: workerKind is shared once a shared worker is initialized", async () => {
    await makeMockEnv();
    const worker = getService("worker_service");
    // Not settled yet.
    expect(worker.workerKind).toBe(null);
    await worker.ensureWorkerStarted();
    expect(worker.state).toBe(WORKER_STATE.INITIALIZED);
    expect(worker.workerKind).toBe("shared");
});

test("J6: workerKind is dedicated when only a plain Worker is available", async () => {
    // No SharedWorker at all: the service must run a dedicated per-tab Worker.
    await makeMockServer();
    patchWithCleanup(browser, { SharedWorker: undefined });
    await makeMockEnv();
    const worker = getService("worker_service");
    await worker.ensureWorkerStarted();
    expect(worker.workerKind).toBe("dedicated");
});

test("J6: workerKind is failed when the worker cannot initialize", async () => {
    patchWithCleanup(WorkerService.prototype, {
        async startWorker() {
            this._state = WORKER_STATE.FAILED;
            this.connectionInitializedDeferred.resolve();
        },
    });
    await makeMockEnv();
    const worker = getService("worker_service");
    await worker.ensureWorkerStarted();
    expect(worker.workerKind).toBe("failed");
});

test("J5: a synchronous SharedWorker constructor throw falls back to a dedicated Worker", async () => {
    await makeMockServer();
    patchWithCleanup(browser, {
        SharedWorker: class {
            constructor() {
                expect.step("shared-worker-throw");
                throw new Error("boom");
            }
        },
        Worker: class extends browser.Worker {
            constructor() {
                super(...arguments);
                expect.step("worker-creation");
            }
        },
    });
    patchWithCleanup(console, { warn: () => {} });
    await makeMockEnv();
    const worker = getService("worker_service");
    await worker.ensureWorkerStarted();
    // Sync throw is routed through onInitError -> dedicated Worker fallback.
    expect(worker.workerKind).toBe("dedicated");
    expect.verifySteps(["shared-worker-throw", "worker-creation"]);
});

test("J5: a synchronous Worker constructor throw ends FAILED without hanging", async () => {
    await makeMockServer();
    patchWithCleanup(browser, {
        SharedWorker: undefined,
        Worker: class {
            constructor() {
                throw new Error("boom");
            }
        },
    });
    const warnings = [];
    patchWithCleanup(console, { warn: (message) => warnings.push(message) });
    await makeMockEnv();
    const worker = getService("worker_service");
    // Must resolve (not hang) even though construction throws synchronously.
    await worker.ensureWorkerStarted();
    expect(worker.state).toBe(WORKER_STATE.FAILED);
});

test("J5: FAILED worker warns once across many sends/handlers", async () => {
    patchWithCleanup(WorkerService.prototype, {
        async startWorker() {
            this._state = WORKER_STATE.FAILED;
            this.connectionInitializedDeferred.resolve();
        },
    });
    const warnings = [];
    patchWithCleanup(console, { warn: (message) => warnings.push(message) });
    await makeMockEnv();
    const worker = getService("worker_service");
    await worker.ensureWorkerStarted();
    await worker.send("BUS:START");
    await worker.send("BUS:START");
    await worker.registerHandler(() => {});
    await runAllTimers();
    const failWarnings = warnings.filter(
        (m) => typeof m === "string" && m.includes("worker messages are dropped"),
    );
    expect(failWarnings).toHaveLength(1);
});
