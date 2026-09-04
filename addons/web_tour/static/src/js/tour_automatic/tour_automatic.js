/** @odoo-module native */
/* eslint-disable no-console -- automated tour runner; step-progress output to console is its purpose */
import hootDom from "@odoo/hoot-dom";
import { enableEventLogs, setupEventActions } from "@odoo/hoot-dom-helpers-events";
import { browser } from "@web/core/browser/browser";
import { RpcEvent } from "@web/core/events";
import { rpcBus } from "@web/core/network";
import { config as transitionConfig } from "@web/core/transition";
import { Macro } from "@web/core/utils/macro";
import { TourStepAutomatic } from "@web_tour/js/tour_automatic/tour_step_automatic";
import { tourState } from "@web_tour/js/tour_state";

// How long `whenClientSettles` waits for the RPCs a previous step started to
// finish.  Same budget as a step's trigger wait, and only ever spent when the
// client is genuinely still working.
const CLIENT_SETTLE_TIMEOUT = 10000;
const EXPIRED = Symbol("expired");
const SETTLED = Symbol("settled");

export class TourAutomatic {
    mode = "auto";
    allowUnload = true;
    unloadWatchdog = null;
    /** ids of the RPCs currently in flight, by `rpcBus` event id. */
    pendingRPCs = new Set();
    constructor(data) {
        Object.assign(this, data);
        this.steps = this.steps.map(
            (step, index) => new TourStepAutomatic(step, this, index),
        );
        this.config = tourState.getCurrentConfig() || {};
    }

    get currentIndex() {
        return tourState.getCurrentIndex();
    }

    get currentStep() {
        return this.steps[this.currentIndex];
    }

    get debugMode() {
        return this.config.debug !== false;
    }

    /**
     * Resolve once the client has no RPC in flight and issues none through the
     * following frame, or after `timeout` if it never gets there.
     *
     * A step's action is dispatched into the page, not awaited by it: clicking
     * a form's statusbar button returns as soon as the click is delivered,
     * while the handler it started goes on to `web_save`, then the button's own
     * call, then a re-read.  The runner used to walk straight into the next
     * step, so a tour could click a *menu* while the record it had just acted
     * on was mid-save -- and the navigation was silently lost, because the
     * outgoing view still had uncommitted work.  Measured on `main_flow_tour`:
     * the "Produce All" click at step 239 was still in `web_save` when step 242
     * clicked the Sales app, and the tour then failed 10 s later at step 246 on
     * a Sales menu that was never opened.  It reproduced on roughly half of the
     * runs, which is exactly what a race looks like from the outside.
     *
     * The frame re-check is the point, not a precaution: a chain issues its
     * next request from the previous response's continuation, so `pendingRPCs`
     * passes through zero *between* two calls of the same chain.  A plain
     * "nothing in flight" test resolves in that gap and races anyway; one frame
     * is longer than the microtask that issues the follow-up, and is what OWL
     * already renders on.
     *
     * `clickbot` tracks in-flight RPCs off the same bus for the same reason.
     */
    async whenClientSettles(timeout = CLIENT_SETTLE_TIMEOUT) {
        if (!this.pendingRPCs.size) {
            // Nothing outstanding: the previous step's post-action frame has
            // already passed, so anything it started has been issued.  Costs
            // nothing on the overwhelming majority of steps.
            return true;
        }
        // The budget is one timer, not a `Date.now()` bound on the loop.  A
        // wall-clock bound cannot end a wait that is itself made of timers:
        // under mocked time -- every hoot test, and any tour driven with
        // `advanceTime` -- the timers fire while `Date.now()` stands still, so
        // the loop re-arms forever and the tour never leaves the step.
        let onExpire;
        const expired = new Promise((resolve) => {
            onExpire = () => resolve(EXPIRED);
        });
        const timer = browser.setTimeout(onExpire, timeout);
        const listeners = [];
        try {
            while (true) {
                if (!this.pendingRPCs.size) {
                    const frame = new Promise((resolve) =>
                        browser.requestAnimationFrame(() => resolve(SETTLED)),
                    );
                    if ((await Promise.race([frame, expired])) === EXPIRED) {
                        break;
                    }
                    if (!this.pendingRPCs.size) {
                        return true;
                    }
                    continue;
                }
                const answered = new Promise((resolve) => {
                    const done = () => resolve(SETTLED);
                    listeners.push(done);
                    rpcBus.addEventListener(RpcEvent.RESPONSE, done);
                });
                if ((await Promise.race([answered, expired])) === EXPIRED) {
                    break;
                }
            }
        } finally {
            browser.clearTimeout(timer);
            for (const done of listeners) {
                rpcBus.removeEventListener(RpcEvent.RESPONSE, done);
            }
        }
        // Whatever is still pending has outlived the budget, so stop counting
        // it: `RPC:REQUEST` is balanced by `RPC:RESPONSE` on every path in
        // `rpc.js` today, including aborts, but a single request that ever
        // escaped that would otherwise make *every* later step pay this
        // timeout again. Presume the stragglers lost and move on -- a bounded
        // wait once, not a bounded wait forever.
        this.pendingRPCs.clear();
        // Not settling is not this function's failure to report: the step is
        // about to look for its trigger and will say what it could not find.
        return false;
    }

    start() {
        setupEventActions(document.createElement("div"), { allowSubmit: true });
        enableEventLogs(this.debugMode);
        const onRPCRequest = (ev) => this.pendingRPCs.add(ev.detail.data.id);
        const onRPCResponse = (ev) => this.pendingRPCs.delete(ev.detail?.data?.id);
        rpcBus.addEventListener(RpcEvent.REQUEST, onRPCRequest);
        rpcBus.addEventListener(RpcEvent.RESPONSE, onRPCResponse);
        const { delayToCheckUndeterminisms, stepDelay } = this.config;
        const macroSteps = this.steps
            .filter((step) => step.index >= this.currentIndex)
            .flatMap((step) => [
                {
                    action: async () => {
                        if (this.debugMode) {
                            console.groupCollapsed(step.describeMe);
                            console.log(step.stringify);
                            if (stepDelay > 0) {
                                await hootDom.delay(stepDelay);
                            }
                            if (step.break) {
                                // eslint-disable-next-line no-debugger
                                debugger;
                            }
                        } else {
                            console.log(step.describeMe);
                        }
                        if (!step.expectUnloadPage) {
                            // The RPC still in flight is the one whose
                            // response navigates away; waiting on it here
                            // lets `beforeunload` fire before the step's own
                            // action has set `allowUnload`.
                            await this.whenClientSettles();
                        }
                    },
                },
                {
                    trigger: step.trigger ? () => step.findTrigger() : null,
                    timeout:
                        step.pause && this.debugMode
                            ? 9999999
                            : step.timeout || this.timeout || 10000,
                    action: async (trigger) => {
                        if (delayToCheckUndeterminisms > 0) {
                            await step.checkForUndeterminisms(
                                trigger,
                                delayToCheckUndeterminisms,
                            );
                        }
                        this.allowUnload = false;
                        if (!step.skipped && step.expectUnloadPage) {
                            this.allowUnload = true;
                            browser.clearTimeout(this.unloadWatchdog);
                            this.unloadWatchdog = browser.setTimeout(() => {
                                const message = `
                                    The key { expectUnloadPage } is defined but page has not been unloaded within 20000 ms.
                                    You probably don't need it.
                                `.replace(/^\s+/gm, "");
                                this.throwError(message);
                            }, 20000);
                        }
                        await step.doAction();
                        if (!this.allowUnload) {
                            // Let the DOM catch up before the next step looks at
                            // it. `Macro.advance` chains straight into
                            // `waitForTrigger`, whose predicate runs SYNCHRONOUSLY
                            // on its first call -- so the next step was inspecting
                            // the page in the same task as the action that had just
                            // changed it, before OWL had rendered anything.
                            //
                            // That is a correctness problem, not a speed one: a
                            // step's guards are decided against a stale DOM. It is
                            // what made `tour_check_modal` pass -- the step clicked
                            // a button behind a dialog because `elementIsInModal`
                            // ran before the dialog it was supposed to notice
                            // existed. One frame is the right amount: OWL schedules
                            // its render with `requestAnimationFrame` during the
                            // action, so a frame requested *after* it is guaranteed
                            // to run once that render has landed.
                            //
                            // Skipped when the step declared `expectUnloadPage`:
                            // the page is navigating away and there is no next
                            // step here to protect.
                            await new Promise((resolve) =>
                                browser.requestAnimationFrame(resolve),
                            );
                        }
                        if (this.debugMode) {
                            console.log(trigger);
                            if (step.skipped) {
                                console.log("This step has been skipped");
                            } else {
                                console.log("This step has run successfully");
                            }
                            console.groupEnd();
                            if (step.pause) {
                                await this.pause();
                            }
                        }
                        tourState.setCurrentIndex(step.index + 1);
                        if (this.allowUnload) {
                            // The step declared `expectUnloadPage`: stop the
                            // macro here and let the navigation happen. Must be
                            // `Macro.STOP` -- any other truthy value still
                            // halts, but only through the deprecated
                            // backward-compat branch, which logs a warning on
                            // every `expectUnloadPage` step of every tour.
                            return Macro.STOP;
                        }
                    },
                },
            ]);

        const end = () => {
            rpcBus.removeEventListener(RpcEvent.REQUEST, onRPCRequest);
            rpcBus.removeEventListener(RpcEvent.RESPONSE, onRPCResponse);
            this.pendingRPCs.clear();
            browser.clearTimeout(this.unloadWatchdog);
            this.unloadWatchdog = null;
            delete window[hootNameSpace];
            transitionConfig.disabled = false;
            tourState.clear();
            //No need to catch error yet.
            window.addEventListener(
                "error",
                (ev) => {
                    ev.preventDefault();
                    ev.stopImmediatePropagation();
                },
                true,
            );
            window.addEventListener(
                "unhandledrejection",
                (ev) => {
                    ev.preventDefault();
                    ev.stopImmediatePropagation();
                },
                true,
            );
        };

        this.macro = new Macro({
            name: this.name,
            steps: macroSteps,
            onError: ({ error }) => {
                if (error.type === "Timeout") {
                    this.throwError(
                        ...this.currentStep.describeWhyIFailed,
                        error.message,
                    );
                } else {
                    this.throwError(error.message);
                }
                end();
            },
            onComplete: () => {
                browser.console.log("tour succeeded");
                // Used to see easily in the python console and to know which tour has been succeeded in suite tours case.
                const succeeded = `║ TOUR ${this.name} SUCCEEDED ║`;
                const msg = [succeeded];
                msg.unshift("╔" + "═".repeat(succeeded.length - 2) + "╗");
                msg.push("╚" + "═".repeat(succeeded.length - 2) + "╝");
                browser.console.log(`\n\n${msg.join("\n")}\n`);
                end();
            },
        });

        const beforeUnloadHandler = () => {
            if (!this.allowUnload) {
                const message = `
                    Be sure to use { expectUnloadPage: true } for any step
                    that involves firing a beforeUnload event.
                    This avoid a non-deterministic behavior by explicitly stopping
                    the tour that might continue before the page is unloaded.
                `.replace(/^\s+/gm, "");
                this.throwError(message);
            }
        };
        window.addEventListener("beforeunload", beforeUnloadHandler);

        if (this.debugMode && this.currentIndex === 0) {
            // Starts the tour with a debugger to allow you to choose devtools configuration.
            // eslint-disable-next-line no-debugger
            debugger;
        }
        transitionConfig.disabled = true;
        const hootNameSpace = hootDom.exposeHelpers(hootDom);
        console.debug(`Hoot DOM helpers available from \`window.${hootNameSpace}\``);
        this.macro.start();
    }

    get describeWhereIFailed() {
        const offset = 3;
        const start = Math.max(this.currentIndex - offset, 0);
        const end = Math.min(this.currentIndex + offset, this.steps.length - 1);
        const result = [];
        for (let i = start; i <= end; i++) {
            const step = this.steps[i];
            const stepString = step.stringify;
            const text = [stepString];
            if (i === this.currentIndex) {
                const line = "-".repeat(10);
                const failing_step = `${line} FAILED: ${step.describeMe} ${line}`;
                text.unshift(failing_step);
                text.push("-".repeat(failing_step.length));
            }
            result.push(...text);
        }
        return result.join("\n");
    }

    /**
     * @param {string} [error]
     */
    throwError(...args) {
        console.groupEnd();
        tourState.setCurrentTourOnError();
        const step = this.currentStep;
        const failed = step
            ? `FAILED: ${step.describeMe}.`
            : `FAILED: after the last step ran (index ${this.currentIndex} of ${this.steps.length}).`;
        // console.error notifies the test runner that the tour failed.
        browser.console.error([failed, ...args].join("\n"));
        // The logged text shows the relative position of the failed step.
        // Useful for finding the failed step.
        browser.console.dir(this.describeWhereIFailed);
        if (this.debugMode) {
            // eslint-disable-next-line no-debugger
            debugger;
        }
    }

    async pause() {
        const styles = [
            "background: black; color: white; font-size: 14px",
            "background: black; color: orange; font-size: 14px",
        ];
        console.log(
            `%cTour is paused. Use %cplay()%c to continue.`,
            styles[0],
            styles[1],
            styles[0],
        );
        await new Promise((resolve) => {
            window.play = () => {
                resolve();
                delete window.play;
            };
        });
    }
}
