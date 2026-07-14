/** @odoo-module native */
import { EventBus } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { Deferred } from "@web/core/utils/concurrency";

/**
 * Main-tab election over the Web Locks API.
 *
 * A single exclusive lock arbitrates the one "main tab" per origin: whichever
 * tab holds it is main, and when it releases the lock (tab closed, `pagehide`,
 * or `unregister()`) the browser hands it to the next waiter, which becomes
 * main. The browser does the arbitration, race-free, with no heartbeats.
 *
 * This replaces the previous three-part design — a `SharedWorker` `ElectionWorker`
 * (strategy A), a localStorage heartbeat election (strategy B), and a facade
 * that picked between them at runtime based on the effective worker kind. That
 * split had a real failure mode: when one tab's `SharedWorker` construction
 * failed and it fell back to the localStorage strategy while its siblings used
 * the worker strategy, two tabs could each believe they were main (duplicate
 * notifications/sounds/ringing). One lock removes that split-brain and behaves
 * identically for shared, dedicated, and failed workers, so `multi_tab` no
 * longer depends on `worker_service` at all.
 *
 * Public API (unchanged — consumers: mail out_of_focus / discuss_core_web / rtc,
 * survey form, voip user_agent, bus outdated_page_watcher / bus_service):
 * - `isOnMainTab(): Promise<boolean>`
 * - `unregister(): void` — terminal: the tab permanently gives up main-tab duties.
 * - `bus`: EventBus emitting "become_main_tab" / "no_longer_main_tab".
 */
const MAIN_TAB_LOCK = "odoo.bus.main_tab";

export const multiTabService = {
    start() {
        const bus = new EventBus();
        const locks = browser.navigator?.locks;
        let isMain = false;
        // Terminal (public `unregister()`, e.g. bus_service on BUS:OUTDATED
        // keeping stale-code tabs out of main-tab duties): a terminated tab must
        // never re-acquire, not even after a bfcache restore.
        let terminated = false;
        // Resolves once the current acquisition attempt has settled our status
        // (main, or queued behind another tab). Recreated on each attempt so
        // `isOnMainTab()` reflects the latest attempt after a bfcache re-acquire.
        let settled = new Deferred();
        // Resolves the held-lock promise to release the lock (give up main).
        // Null when this tab does not hold the lock.
        let releaseHeld = null;
        // Aborts a pending (queued) acquisition; fresh per attempt.
        let abortController = null;
        // Monotonic token identifying the current acquisition attempt. Bumped by
        // every `acquire()` and by `deactivate()`, so a lock grant that lands
        // after its attempt was superseded (a bfcache re-acquire) or torn down
        // (`deactivate`/`unregister`) can be recognised and dropped. The
        // fast-path `ifAvailable` request carries no abort signal (the spec
        // forbids combining it with `ifAvailable`), so this token is the only
        // thing that can stop its callback from seizing the lock on a dead tab.
        let attempt = 0;

        function becomeMain(myAttempt) {
            if (terminated || myAttempt !== attempt) {
                // The attempt was terminated or superseded before the browser
                // granted the lock. Returning without a pending promise releases
                // the lock synchronously so the next waiter can take over;
                // seizing it here would wedge the election (the tab never runs
                // main-tab duties yet holds the lock forever).
                return;
            }
            isMain = true;
            settled.resolve();
            bus.trigger("become_main_tab");
            // Keeping this promise pending is what holds the lock; resolving it
            // (releaseHeld) releases the lock so the next waiter can take over.
            const held = new Deferred();
            releaseHeld = () => held.resolve();
            return held;
        }

        function ignoreAbort(error) {
            if (error?.name !== "AbortError") {
                throw error;
            }
        }

        function acquire() {
            if (terminated) {
                settled.resolve();
                return;
            }
            if (!locks) {
                // No Web Locks API (very old browser): degrade to "this tab is
                // main" so a single-tab user still gets notifications/sounds.
                // The rare no-locks multi-tab case may duplicate them — an
                // acceptable fallback for a browser this fork does not target.
                if (!isMain) {
                    isMain = true;
                    bus.trigger("become_main_tab");
                }
                settled.resolve();
                return;
            }
            const myAttempt = ++attempt;
            abortController = new AbortController();
            const { signal } = abortController;
            // Fast path: try to grab the lock immediately so our status settles
            // without waiting. If another tab already holds it, settle "not
            // main" now and queue a blocking request for when it is released.
            //
            // The Web Locks spec forbids combining `signal` with `ifAvailable`
            // (it throws NotSupportedError), and it isn't needed here: an
            // `ifAvailable` request never waits, so there is nothing to abort,
            // and once granted the lock is held by `becomeMain`'s pending
            // promise and released via `releaseHeld` — not via the signal. Only
            // the blocking request below waits, so only it takes the signal.
            locks
                .request(MAIN_TAB_LOCK, { ifAvailable: true }, (lock) => {
                    if (lock) {
                        return becomeMain(myAttempt);
                    }
                    if (terminated || myAttempt !== attempt) {
                        return;
                    }
                    settled.resolve();
                    locks
                        .request(MAIN_TAB_LOCK, { signal }, () => becomeMain(myAttempt))
                        .catch(ignoreAbort);
                })
                .catch(ignoreAbort);
        }

        function deactivate() {
            // Give up main (or stop waiting), but keep the right to re-acquire
            // on a bfcache `pageshow`. `no_longer_main_tab` fires synchronously
            // so `isOnMainTab()` reflects the change immediately.
            if (isMain) {
                isMain = false;
                bus.trigger("no_longer_main_tab");
            }
            // Invalidate the in-flight attempt: a fast-path (`ifAvailable`) grant
            // cannot be aborted via the signal, so bumping the token is what
            // stops its callback from re-seizing the lock on this torn-down tab.
            attempt++;
            releaseHeld?.();
            releaseHeld = null;
            abortController?.abort();
            abortController = null;
        }

        browser.addEventListener("pagehide", deactivate);
        browser.addEventListener("pageshow", (ev) => {
            if (ev.persisted && !terminated) {
                settled = new Deferred();
                acquire();
            }
        });

        acquire();

        return {
            bus,
            async isOnMainTab() {
                if (terminated) {
                    return false;
                }
                await settled;
                return isMain;
            },
            unregister() {
                terminated = true;
                deactivate();
                settled.resolve();
            },
        };
    },
};

registry.category("services").add("multi_tab", multiTabService);
