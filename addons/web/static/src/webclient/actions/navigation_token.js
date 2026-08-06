// @ts-check
/** @odoo-module native */

/** @module @web/webclient/actions/navigation_token */

import { SupersededError } from "@web/core/utils/concurrency";

/**
 * THE navigation-supersession authority of the action pipeline.
 *
 * The pipeline used to guard each of its stages with a mechanism of its own —
 * a `KeepLast` for the load stage, a bare counter for `loadState`'s
 * reconstruction, a rejected `Deferred` for the skeleton wait — so "was my
 * navigation cancelled?" had a different answer depending on where it died.
 * This module replaces the *counters*: one monotonic epoch, minted once per
 * navigation entry point (`doAction` / `switchView` / `restore` /
 * `loadState`), and one cancellation outcome, {@link SupersededError}.
 *
 * The epoch answers "is this still the navigation the user wants?"; it does
 * not arbitrate the mount stage. Once a dispatch has published its
 * `ACTION_MANAGER:UPDATE`, the container's re-render is what destroys a
 * superseded component, and `ActionDispatch.discard()` translates that
 * destruction into the same `SupersededError` — same outcome, different
 * sensor.
 */
export class NavigationToken {
    /**
     * @param {NavigationTracker} tracker
     * @param {number} epoch
     */
    constructor(tracker, epoch) {
        this._tracker = tracker;
        this.epoch = epoch;
    }

    /**
     * Whether no newer navigation has been minted since this one.
     *
     * @returns {boolean}
     */
    isCurrent() {
        return this._tracker.epoch === this.epoch;
    }

    /**
     * The checkpoint form of {@link isCurrent}: one error type, everywhere.
     *
     * @throws {SupersededError}
     */
    throwIfSuperseded() {
        if (!this.isCurrent()) {
            throw new SupersededError();
        }
    }

    /**
     * Await `promise` on behalf of this navigation. Rejects with
     * {@link SupersededError} the moment a newer navigation is minted — not
     * when `promise` eventually settles — and drops `promise`'s own
     * settlement if it arrives after that. Exactly `KeepLast#add` with
     * `rejectSuperseded`, re-expressed against a token so intermediate
     * checkpoints (`isCurrent` between stages) read the same clock.
     *
     * @template T
     * @param {Promise<T>} promise
     * @returns {Promise<T>}
     */
    settle(promise) {
        return this._tracker._settle(this, promise);
    }
}

export class NavigationTracker {
    constructor() {
        this._epoch = 0;
        /** @type {((reason: unknown) => void) | null} */
        this._rejectPending = null;
    }

    /**
     * @returns {number}
     */
    get epoch() {
        return this._epoch;
    }

    /**
     * Open a NEW navigation: every older token stops being current, and a
     * pending {@link NavigationToken#settle} is rejected eagerly so its
     * awaiter unwinds now rather than when its promise settles.
     *
     * @returns {NavigationToken}
     */
    mint() {
        this._epoch++;
        if (this._rejectPending) {
            this._rejectPending(new SupersededError());
            this._rejectPending = null;
        }
        return new NavigationToken(this, this._epoch);
    }

    /**
     * The token of the navigation already under way — reads the clock without
     * advancing it, for guards that must observe ("did anything newer start
     * while I waited?") without cancelling anything themselves.
     *
     * @returns {NavigationToken}
     */
    snapshot() {
        return new NavigationToken(this, this._epoch);
    }

    /**
     * mint + settle in one move — the drop-in shape for the load stage's old
     * `keepLast.add(promise)` call sites.
     *
     * @template T
     * @param {Promise<T>} promise
     * @returns {Promise<T>}
     */
    guard(promise) {
        return this.mint().settle(promise);
    }

    /**
     * @template T
     * @param {NavigationToken} token
     * @param {Promise<T>} promise
     * @returns {Promise<T>}
     */
    _settle(token, promise) {
        return new Promise((resolve, reject) => {
            if (!token.isCurrent()) {
                reject(new SupersededError());
                return;
            }
            this._rejectPending = reject;
            promise.then(
                (value) => {
                    if (token.isCurrent()) {
                        this._rejectPending = null;
                        resolve(value);
                    }
                },
                (reason) => {
                    if (token.isCurrent()) {
                        this._rejectPending = null;
                        reject(reason);
                    }
                },
            );
        });
    }
}
