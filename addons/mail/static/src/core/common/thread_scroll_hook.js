/** @odoo-module native */
import { Record } from "@mail/core/common/record";
import { useVisible } from "@mail/utils/common/hooks";
import {
    onWillDestroy,
    onWillPatch,
    onWillUpdateProps,
    toRaw,
    useEffect,
} from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { Deferred } from "@web/core/utils/concurrency";

/** Distance (px) from the "present" edge under which the view counts as at bottom. */
export const AT_BOTTOM_THRESHOLD = 30;

/**
 * @typedef {Object} ScrollMetrics
 * @property {number} scrollTop
 * @property {number} scrollHeight
 * @property {number} clientHeight
 */

/**
 * Whether a message list is scrolled to its "present" edge (bottom in "asc"
 * order, top in "desc" order). While newer messages can still be loaded the
 * present edge is not actually the present, so this is always false then.
 *
 * @param {ScrollMetrics & {
 *  order: "asc"|"desc",
 *  loadNewer: boolean,
 *  threshold?: number,
 * }} param0
 * @returns {boolean}
 */
export function isScrolledToBottom({
    order,
    scrollTop,
    scrollHeight,
    clientHeight,
    loadNewer,
    threshold = AT_BOTTOM_THRESHOLD,
}) {
    if (loadNewer) {
        return false;
    }
    return order === "asc"
        ? scrollHeight - scrollTop - clientHeight < threshold
        : scrollTop < threshold;
}

/**
 * Scroll position to persist on the thread record: the special "bottom" marker
 * when at the present edge, otherwise the distance from the present edge (a
 * plain scrollTop in "asc" order, its mirror in "desc" order) so the position
 * survives content growing on the other side.
 *
 * @param {ScrollMetrics & { order: "asc"|"desc", loadNewer: boolean }} param0
 * @returns {number|"bottom"}
 */
export function computeSavedScrollTop({
    order,
    scrollTop,
    scrollHeight,
    clientHeight,
    loadNewer,
}) {
    if (
        isScrolledToBottom({ order, scrollTop, scrollHeight, clientHeight, loadNewer })
    ) {
        return "bottom";
    }
    return order === "asc" ? scrollTop : scrollHeight - scrollTop - clientHeight;
}

/**
 * Clamp a requested scroll target to the reachable range and report whether
 * scrolling there is a no-op. Browsers never fire "scrollend" for a no-op
 * smooth scroll, so callers must resolve immediately in that case.
 *
 * @param {ScrollMetrics & { value: number }} param0
 * @returns {{ target: number, noMovement: boolean }}
 */
export function computeSmoothScrollTarget({
    value,
    scrollTop,
    scrollHeight,
    clientHeight,
}) {
    const target = Math.min(Math.max(value, 0), scrollHeight - clientHeight);
    return { target, noMovement: Math.abs(scrollTop - target) < 1 };
}

/**
 * Decision logic of the scroll state machine for one render: given the
 * previous render's bookkeeping (snapshot, persistent message boundaries,
 * lastSetValue) and the current DOM metrics, decide how the scroll position
 * must be adjusted. Pure: no DOM, no records.
 *
 * @param {Object} param0
 * @param {"asc"|"desc"} param0.order
 * @param {{ scrollTop: number, scrollHeight: number }} [param0.snapshot]
 *  pre-patch metrics captured in `onWillPatch` (behavior 2)
 * @param {number} param0.scrollHeight current scrollHeight
 * @param {number} param0.clientHeight current clientHeight
 * @param {boolean} param0.olderMessagesLoaded older messages appeared since last render
 * @param {boolean} param0.newerMessagesLoaded newer messages appeared since last render
 * @param {boolean} param0.hadLoadNewer whether newer messages could be loaded at last render
 * @param {number|string|undefined} param0.threadScrollTop persisted `thread.scrollTop`
 *  (number, "bottom", "bottom-smooth" or undefined)
 * @param {boolean} param0.isHighlighting a message highlight is in progress (behavior 5)
 * @param {number} [param0.lastSetValue] last scroll value applied by the machine itself
 * @param {boolean} param0.isSmoothScrolling a smooth scroll animation is in flight
 * @returns {{ type: "none" }
 *  | { type: "snapshot-top", value: number }
 *  | { type: "snapshot-bottom", value: number }
 *  | { type: "restore", value: number, smooth: boolean }}
 */
export function computeScrollAction({
    order,
    snapshot,
    scrollHeight,
    clientHeight,
    olderMessagesLoaded,
    newerMessagesLoaded,
    hadLoadNewer,
    threadScrollTop,
    isHighlighting,
    lastSetValue,
    isSmoothScrolling,
}) {
    const scrollTopIsBottom =
        typeof threadScrollTop === "string" && threadScrollTop.includes("bottom");
    const messagesAtTop =
        (order === "asc" && olderMessagesLoaded) ||
        (order === "desc" && newerMessagesLoaded);
    const messagesAtBottom =
        (order === "desc" && olderMessagesLoaded) ||
        (order === "asc" &&
            newerMessagesLoaded &&
            (hadLoadNewer || !scrollTopIsBottom));
    if (snapshot && messagesAtTop) {
        // Extra content was inserted above the viewport: compensate its height
        // so the messages already on screen visually stay in place.
        return {
            type: "snapshot-top",
            value: snapshot.scrollTop + scrollHeight - snapshot.scrollHeight,
        };
    }
    if (snapshot && messagesAtBottom) {
        // Extra content was inserted below the viewport: keeping the same
        // scrollTop keeps the messages on screen in place.
        return { type: "snapshot-bottom", value: snapshot.scrollTop };
    }
    if (isHighlighting || threadScrollTop === undefined) {
        // Highlighting takes priority (behavior 5), and without a persisted
        // position there is nothing to restore.
        return { type: "none" };
    }
    let value;
    if (scrollTopIsBottom) {
        value = order === "asc" ? scrollHeight - clientHeight : 0;
    } else {
        value =
            order === "asc"
                ? threadScrollTop
                : scrollHeight - threadScrollTop - clientHeight;
    }
    if (
        (lastSetValue !== undefined && Math.abs(lastSetValue - value) <= 1) ||
        isSmoothScrolling
    ) {
        // Setting the same value twice in a row could override a concurrent
        // outside change, and an in-flight smooth scroll must not be hijacked.
        return { type: "none" };
    }
    return {
        type: "restore",
        value,
        smooth:
            typeof threadScrollTop === "string" && threadScrollTop.includes("smooth"),
    };
}

/**
 * Scroll state machine of a message list. The scroll is managed in several
 * different ways:
 *
 * 1. When the user first accesses a thread with unread messages, or when
 *    the user goes back to a thread with new unread messages, it should
 *    scroll to the position of the first unread message if there is one.
 * 2. When loading older or newer messages, the messages already on screen
 *    should visually stay in place. When the extra messages are added at
 *    the bottom (chatter loading older, or channel loading newer) the same
 *    scroll top position should be kept, and when the extra messages are
 *    added at the top (chatter loading newer, or channel loading older),
 *    the extra height from the extra messages should be compensated in the
 *    scroll position.
 * 3. When the scroll is at the bottom, it should stay at the bottom when
 *    there is a change of height: new messages, images loaded, ...
 * 4. When the user goes back and forth between threads, it should restore
 *    the last scroll position of each thread.
 * 5. When currently highlighting a message it takes priority to allow the
 *    highlighted message to be scrolled to.
 */
export class ThreadScroll {
    /** @type {Deferred|undefined} resolves when the in-flight smooth scroll settles */
    smoothScrollingDeferred;
    /** @type {number|undefined} */
    smoothScrollingTimeout;
    isSmoothScrolling = false;

    /** @param {import("@mail/core/common/thread_scroll_hook").ThreadScrollOptions} options */
    constructor(options) {
        this.options = options;
        this.applyScroll = this.applyScroll.bind(this);
        this.saveScroll = this.saveScroll.bind(this);
        /**
         * Last scroll value that was automatically set. This prevents from
         * setting the same value 2 times in a row. This is not supposed to have
         * an effect, unless the value was changed from outside in the meantime,
         * in which case resetting the value would incorrectly override the
         * other change. This should give enough time to scroll/resize event to
         * register the new scroll value.
         */
        this.lastSetValue = undefined;
        /**
         * The snapshot mechanism (point 2) should only apply after the messages
         * have been loaded and displayed at least once. Technically this is
         * after the first patch following when `mountedAndLoaded` is true. This
         * is what this variable holds.
         */
        this.loadedAndPatched = false;
        /**
         * The snapshot of current scrollTop and scrollHeight for the purpose
         * of keeping messages in place when loading older/newer (point 2).
         */
        this.snapshot = undefined;
        /**
         * The newest message that is already rendered, useful to detect
         * whether newer messages have been loaded since last render to decide
         * when to apply the snapshot to keep messages in place (point 2).
         */
        this.newestPersistentMessage = undefined;
        /**
         * The oldest message that is already rendered, useful to detect
         * whether older messages have been loaded since last render to decide
         * when to apply the snapshot to keep messages in place (point 2).
         */
        this.oldestPersistentMessage = undefined;
        /**
         * Whether it was possible to load newer messages in the last rendered
         * state, useful to decide when to apply the snapshot to keep messages
         * in place (point 2).
         */
        this.loadNewer = undefined;
    }

    get el() {
        return this.options.scrollableRef.el;
    }

    get isAtBottom() {
        const el = this.el;
        return isScrolledToBottom({
            order: this.options.getOrder(),
            scrollTop: el.scrollTop,
            scrollHeight: el.scrollHeight,
            clientHeight: el.clientHeight,
            loadNewer: this.loadNewer,
        });
    }

    applyScroll() {
        if (!this.options.getThread().isLoaded || !this.options.getMountedAndLoaded()) {
            this.reset();
            return;
        }
        // Use toRaw() to prevent scroll check from triggering renders.
        const thread = toRaw(this.options.getThread());
        // Routed through the component so `patch()`es and subclasses can
        // override the contextual step of the pipeline.
        this.options.applyScrollContextually(thread);
        this.snapshot = undefined;
        this.newestPersistentMessage = thread.newestPersistentMessage;
        this.oldestPersistentMessage = thread.oldestPersistentMessage;
        this.loadNewer = thread.loadNewer;
        if (!this.loadedAndPatched) {
            this.loadedAndPatched = true;
            this.loadOlderState.ready = true;
            this.loadNewerState.ready = true;
        }
    }

    /**
     * Default contextual scroll application (behaviors 2 to 5). Overridable
     * mid-pipeline through the owning component (e.g. discuss scrolls to the
     * first unread message instead).
     *
     * @param {import("models").Thread} thread
     */
    applyScrollContextually(thread) {
        const el = this.el;
        const action = computeScrollAction({
            order: this.options.getOrder(),
            snapshot: this.snapshot,
            scrollHeight: el.scrollHeight,
            clientHeight: el.clientHeight,
            olderMessagesLoaded:
                thread.oldestPersistentMessage?.id < this.oldestPersistentMessage?.id,
            newerMessagesLoaded:
                thread.newestPersistentMessage?.id > this.newestPersistentMessage?.id,
            hadLoadNewer: this.loadNewer,
            threadScrollTop: thread.scrollTop,
            isHighlighting: Boolean(this.options.getHighlightedMessageId()),
            lastSetValue: this.lastSetValue,
            isSmoothScrolling: this.isSmoothScrolling,
        });
        switch (action.type) {
            case "snapshot-top":
            case "snapshot-bottom":
                this.setScroll(action.value);
                break;
            case "restore":
                this.setScroll(action.value, { smooth: action.smooth });
                break;
        }
    }

    reset() {
        this.options.onReset();
        this.loadOlderState.ready = false;
        this.loadNewerState.ready = false;
        this.lastSetValue = undefined;
        this.snapshot = undefined;
        this.newestPersistentMessage = undefined;
        this.oldestPersistentMessage = undefined;
        this.loadedAndPatched = false;
        this.loadNewer = false;
    }

    saveScroll() {
        const thread = toRaw(this.options.getThread());
        const el = this.el;
        thread.scrollTop = computeSavedScrollTop({
            order: this.options.getOrder(),
            scrollTop: el.scrollTop,
            scrollHeight: el.scrollHeight,
            clientHeight: el.clientHeight,
            loadNewer: this.loadNewer,
        });
    }

    /**
     * @param {number} value
     * @param {Object} [param1]
     * @param {boolean} [param1.smooth=false]
     */
    setScroll(value, { smooth = false } = {}) {
        if (smooth) {
            const el = this.el;
            browser.clearTimeout(this.smoothScrollingTimeout);
            // Resolve a superseded smooth scroll: its "scrollend" might never
            // come, and awaiters (loadOlder/loadNewer) must not hang on it.
            this.smoothScrollingDeferred?.resolve();
            const deferred = new Deferred();
            this.smoothScrollingDeferred = deferred;
            this.isSmoothScrolling = true;
            const onSmoothScrollingEnd = () => {
                browser.clearTimeout(this.smoothScrollingTimeout);
                document.removeEventListener("scrollend", onScrollEnd, {
                    capture: true,
                });
                if (this.smoothScrollingDeferred === deferred) {
                    this.smoothScrollingDeferred = undefined;
                    this.isSmoothScrolling = false;
                }
                deferred.resolve();
            };
            const onScrollEnd = (ev) => {
                // "scrollend" is captured document-wide and fires for ANY
                // scrollable (sidebar, another chat window, the chatter):
                // only OUR element's scrollend may settle this animation —
                // a foreign one would drop the isSmoothScrolling guard and
                // un-gate loadOlder/loadNewer mid-animation
                if (ev.target !== el) {
                    return;
                }
                onSmoothScrollingEnd();
            };
            const { noMovement } = computeSmoothScrollTarget({
                value,
                scrollTop: el.scrollTop,
                scrollHeight: el.scrollHeight,
                clientHeight: el.clientHeight,
            });
            if (noMovement) {
                // No movement will occur: browsers never fire "scrollend" for
                // a no-op scroll, which would leave the deferred pending and
                // freeze infinite scroll (loadOlder/loadNewer await it).
                onSmoothScrollingEnd();
            } else if ("onscrollend" in window) {
                document.addEventListener("scrollend", onScrollEnd, {
                    capture: true,
                });
                // Safety net: a missed "scrollend" (interrupted animation,
                // scrollable removed mid-scroll, ...) must never wedge the
                // deferred forever.
                this.smoothScrollingTimeout = browser.setTimeout(
                    onSmoothScrollingEnd,
                    3000,
                );
            } else {
                // To remove when safari will support the "scrollend" event.
                this.smoothScrollingTimeout = browser.setTimeout(
                    onSmoothScrollingEnd,
                    250,
                );
            }
        }
        this.el.scrollTo({
            behavior: smooth ? "smooth" : undefined,
            top: value,
        });
        this.lastSetValue = value;
        this.options.getMessageHighlight()?.startupDeferred?.resolve();
        this.saveScroll();
    }
}

/**
 * @typedef {Object} ThreadScrollOptions
 * @property {{ el: HTMLElement|null }} scrollableRef reference to the scrollable element
 * @property {() => import("models").Thread} getThread current thread (the hook also reads
 *  `nextProps.thread` in `onWillUpdateProps`, so the component must receive the thread as
 *  a `thread` prop)
 * @property {() => "asc"|"desc"} getOrder
 * @property {() => boolean} getMountedAndLoaded
 * @property {() => Object} getMessageHighlight message highlight state
 *  (`scrollPromise` / `startupDeferred` owner), if any
 * @property {() => number|undefined} getHighlightedMessageId
 * @property {(thread: import("models").Thread) => void} applyScrollContextually the
 *  contextual step of the pipeline, routed through the component so that overrides
 *  (subclasses, `patch()`es) can intercept it
 * @property {() => void} onReset component-side state to reset alongside the machine
 * @property {() => void} onResize called when the scrollable is resized
 * @property {(ev: Event) => void} onScroll scroll listener to attach to the scrollable
 */

/**
 * Set up the scroll state machine of a message list on the current component:
 * scroll application on every patch, scroll persistence, smooth scrolling
 * lifecycle and infinite-scroll (load older/newer) wiring.
 *
 * @param {ThreadScrollOptions} options
 * @returns {ThreadScroll}
 */
export function useThreadScroll(options) {
    const scroll = new ThreadScroll(options);
    scroll.loadOlderState = useVisible(
        "load-older",
        async () => {
            await Promise.all([
                options.getMessageHighlight()?.scrollPromise,
                scroll.smoothScrollingDeferred,
            ]);
            if (scroll.loadOlderState.isVisible) {
                toRaw(options.getThread()).fetchMoreMessages();
            }
        },
        { ready: false },
    );
    scroll.loadNewerState = useVisible(
        "load-newer",
        async () => {
            await Promise.all([
                options.getMessageHighlight()?.scrollPromise,
                scroll.smoothScrollingDeferred,
            ]);
            if (scroll.loadNewerState.isVisible) {
                toRaw(options.getThread()).fetchMoreMessages("newer");
            }
        },
        { ready: false },
    );
    /**
     * These states need to be immediately reset when the value changes on
     * the record, because the transition is important, not only the final
     * value. If resetting is depending on the update cycle, it can happen
     * that the value quickly changes and then back again before there is
     * any mounting/patching, and the change would therefore be undetected.
     */
    let stopOnChange = Record.onChange(options.getThread(), "isLoaded", () => {
        if (!options.getThread().isLoaded || !options.getMountedAndLoaded()) {
            scroll.reset();
        }
    });
    onWillUpdateProps((nextProps) => {
        if (nextProps.thread.notEq(options.getThread())) {
            stopOnChange();
            stopOnChange = Record.onChange(nextProps.thread, "isLoaded", () => {
                if (!nextProps.thread.isLoaded || !options.getMountedAndLoaded()) {
                    scroll.reset();
                }
            });
        }
    });
    onWillDestroy(() => stopOnChange());
    onWillPatch(() => {
        if (!scroll.loadedAndPatched) {
            return;
        }
        scroll.snapshot = {
            scrollHeight: scroll.el.scrollHeight,
            scrollTop: scroll.el.scrollTop,
        };
    });
    useEffect(scroll.applyScroll);
    const observer = new ResizeObserver(() => {
        options.onResize();
        scroll.applyScroll();
    });
    useEffect(
        (el, mountedAndLoaded) => {
            if (el && mountedAndLoaded) {
                el.addEventListener("scroll", options.onScroll);
                observer.observe(el);
                return () => {
                    observer.unobserve(el);
                    el.removeEventListener("scroll", options.onScroll);
                };
            }
        },
        () => [options.scrollableRef.el, options.getMountedAndLoaded()],
    );
    return scroll;
}
