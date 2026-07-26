// @ts-check
/** @odoo-module native */

/** @module @web/webclient/service_worker_service - Registers the backend service worker, keeps it updated, and exposes its activation as a promise */

import { browser } from "@web/core/browser/browser";
import { RpcEvent } from "@web/core/events";
import { rpcBus } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { Deferred } from "@web/core/utils/concurrency";

/**
 * Interval between proactive service-worker update checks.  Conservative:
 * the check is a conditional request the browser answers from its HTTP
 * cache / the server answers 304 to when the script is unchanged.
 */
const SERVICE_WORKER_UPDATE_INTERVAL = 6 * 60 * 60 * 1000; // 6 hours

/**
 * Upper bound on how long registration waits for ``serviceWorker.ready``.
 * That promise never settles when a worker fails to activate, and it gates
 * the ``finally`` that settles ``activated`` — see the INVARIANT below.
 */
const SERVICE_WORKER_READY_TIMEOUT = 20 * 1000; // 20 seconds

/**
 * Wires the service-worker update lifecycle onto a registration.
 *
 * Without this, an updated worker sits in the ``waiting`` state until EVERY
 * tab under the scope has closed — days for a long-lived backoffice SPA —
 * so service-worker fixes never ship, and the activate-time purge of
 * superseded asset bundles is deferred just as long (until browser quota
 * eviction nukes the whole origin, IndexedDB RPC cache included).
 *
 * Two mechanisms:
 *
 * - When a new worker version reaches the ``installed`` state while another
 *   version is active (i.e. an UPDATE, not the first install — first
 *   installs keep the natural lifecycle), it is told to ``skipWaiting()``
 *   and takes over immediately.  Mid-session activation is safe here: the
 *   worker's fetch handlers are stateless (pure URL-pattern routing over
 *   persistent caches), so swapping versions between two fetches cannot
 *   corrupt in-flight state.
 * - Proactive ``registration.update()`` checks: the browser only re-fetches
 *   the worker script on navigation, which a long-lived SPA tab never
 *   performs.  Poll on a conservative cadence, plus one check each time the
 *   tab becomes visible again (both cheap and standard).
 *
 * Exported for unit tests (exercised with a mocked registration).
 *
 * @param {ServiceWorkerRegistration} registration
 * @returns {void}
 */
export function watchServiceWorkerUpdates(registration) {
    /** @param {ServiceWorker | null} worker */
    const promoteWhenInstalled = (worker) => {
        if (!worker) {
            return;
        }
        const promote = () => {
            // ``registration.active`` distinguishes an update from the very
            // first install: on first install there is no active version to
            // supersede and skipping the waiting state is pointless churn.
            if (worker.state === "installed" && registration.active) {
                worker.postMessage({ type: "SKIP_WAITING" });
            }
        };
        worker.addEventListener("statechange", promote);
        // The worker may already be past ``installing`` (e.g. it was found
        // parked in ``registration.waiting`` on boot).
        promote();
    };
    // An updated worker may already be waiting from a previous session.
    promoteWhenInstalled(registration.waiting);
    registration.addEventListener("updatefound", () =>
        promoteWhenInstalled(registration.installing),
    );
    const checkForUpdate = () =>
        registration.update().catch(() => {
            // Offline or server unreachable — the next check will retry.
        });
    browser.setInterval(checkForUpdate, SERVICE_WORKER_UPDATE_INTERVAL);
    // ``visibilitychange`` fires on ``document`` and bubbles to ``window``,
    // which the ``browser`` facade's ``addEventListener`` is bound to.
    browser.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") {
            checkForUpdate();
        }
    });
}

/**
 * Register the Odoo service worker for the /odoo scope and settle
 * ``activatedDeferred`` once it is active.
 *
 * INVARIANT — the deferred MUST always settle, on every exit path.
 * It is not a private detail: ``mail``'s ``_doSubscribePush`` /
 * ``_doUnsubscribePush`` both ``await`` it *inside* a ``Mutex``, so a
 * deferred left pending does not merely stall push registration, it wedges
 * that mutex for the whole session — every later (un)subscription queues
 * behind a slot that never frees.
 *
 * Three exits used to leave it pending forever, all silent:
 *   - no ``navigator.serviceWorker`` at all (a non-secure context: plain
 *     HTTP on a non-loopback origin, where ``Notification`` and
 *     ``navigator.permissions`` still exist, so mail's permission-change
 *     handler does reach the push path);
 *   - ``register()`` rejecting (the script 404s, wrong MIME, disabled by
 *     policy) — the ``catch`` logged and returned;
 *   - ``serviceWorker.ready`` never resolving, which happens when a worker
 *     fails to activate (a throwing ``install`` handler leaves the
 *     registration redundant).
 *
 * The ``finally`` covers the first two; the bounded race covers the third.
 * Settling is the right resolution rather than rejecting: every consumer
 * already degrades gracefully when there is no service worker (mail's
 * ``pushManager()`` optional-chains it and its callers return early).
 *
 * Exported for unit tests.
 *
 * @param {Deferred} activatedDeferred settled on every exit path
 * @returns {Promise<ServiceWorkerRegistration | undefined>}
 */
export async function registerServiceWorker(activatedDeferred) {
    // ``browser.navigator`` rather than the bare global: it is the same
    // object (the facade captures it), but going through the facade matches
    // the rest of the codebase — mail reads
    // ``browser.navigator.serviceWorker`` — and is patchable via
    // ``patchWithCleanup(browser, ...)``.
    const { serviceWorker } = browser.navigator;
    try {
        if (!serviceWorker) {
            return;
        }
        const registration = await serviceWorker.register("/web/service-worker.js", {
            scope: "/odoo",
        });
        watchServiceWorkerUpdates(registration);
        if (registration.active && registration.active.state === "activated") {
            activatedDeferred.resolve();
        } else {
            const sw =
                registration.installing || registration.waiting || registration.active;
            // ``sw`` is null if the registration was torn down in between;
            // the ``finally`` still settles the deferred.
            sw?.addEventListener("statechange", (e) => {
                if (/** @type {any} */ (e.target).state === "activated") {
                    activatedDeferred.resolve();
                }
            });
        }
        await Promise.race([
            serviceWorker.ready,
            new Promise((resolve) =>
                browser.setTimeout(resolve, SERVICE_WORKER_READY_TIMEOUT),
            ),
        ]);
        if (!serviceWorker.controller) {
            // https://stackoverflow.com/questions/51597231/register-service-worker-after-hard-refresh
            rpcBus.trigger(RpcEvent.CLEAR_CACHES);
        }
        return registration;
    } catch (error) {
        console.error("Service worker registration failed, error:", error);
    } finally {
        // No-op on the happy path (already resolved above); load-bearing on
        // every failure path. See the INVARIANT note.
        activatedDeferred.resolve();
    }
}

/**
 * Owns the backend service worker's lifetime.
 *
 * This lived on the ``WebClient`` component (~40% of that file) and its
 * activation deferred was reached by ``mail`` through a
 * ``patch(WebClient.prototype, ...)`` — a cross-addon lifetime contract riding
 * on a component instance field, which is why the INVARIANT above needed
 * restating there. As a service the contract is declared: consumers depend on
 * ``service_worker`` and read ``activated``.
 *
 * It must stay under ``webclient/`` rather than ``services/``: the manifest
 * puts ``web/static/src/services/**`` in ``web.assets_frontend`` too, so a
 * service there would register this ``/odoo``-scoped worker on every public
 * website page. ``webclient/**`` is backend-only.
 */
export const serviceWorkerService = {
    start() {
        const activatedDeferred = new Deferred();
        // Fire-and-forget: nothing may block on registration/activation. If the
        // install stalls, awaiting it here would stall service startup and
        // leave a blank page. ``registerServiceWorker`` catches its own errors.
        registerServiceWorker(activatedDeferred);
        return {
            /**
             * Resolves once the worker is active — or once we know it never
             * will be. Never rejects: see the INVARIANT above.
             * @type {Promise<void>}
             */
            activated: activatedDeferred,
        };
    },
};

registry.category("services").add("service_worker", serviceWorkerService);
