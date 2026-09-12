// @ts-check
/** @odoo-module native */
import { Record } from "@mail/core/common/record";
import { useVisible } from "@mail/utils/common/hooks";
import { awaitScrollEnd } from "@mail/utils/common/misc";
import {
    onWillDestroy,
    onWillPatch,
    onWillUpdateProps,
    toRaw,
    useEffect,
} from "@odoo/owl";
import { makeLogger } from "@web/core/debug/debug_logger";

const log = makeLogger("mail.thread.scroll");

export const AT_BOTTOM_THRESHOLD = 30;

/**
 * @typedef {Object} ScrollMetrics
 * @property {number} scrollTop
 * @property {number} scrollHeight
 * @property {number} clientHeight
 */
/**
 * @param {ScrollMetrics & { order: "asc"|"desc", loadNewer: boolean, threshold?: number, }} param0
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
 * @param {Object} param0
 * @param {"asc"|"desc"} param0.order
 * @param {{ scrollTop: number, scrollHeight: number }} [param0.snapshot]
 * @param {number} param0.scrollHeight
 * @param {number} param0.clientHeight
 * @param {boolean} param0.olderMessagesLoaded
 * @param {boolean} param0.newerMessagesLoaded
 * @param {boolean} param0.hadLoadNewer
 * @param {number|string|undefined} param0.threadScrollTop
 * @param {boolean} param0.isHighlighting
 * @param {number} [param0.lastSetValue]
 * @param {boolean} param0.isSmoothScrolling
 * @returns {{ type: "none" } | { type: "snapshot-top", value: number } | { type: "snapshot-bottom", value: number } | { type: "restore", value: number, smooth: boolean }}
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
        return {
            type: "snapshot-top",
            value: snapshot.scrollTop + scrollHeight - snapshot.scrollHeight,
        };
    }
    if (snapshot && messagesAtBottom) {
        return { type: "snapshot-bottom", value: snapshot.scrollTop };
    }
    if (isHighlighting || threadScrollTop === undefined) {
        return { type: "none" };
    }
    let value;
    if (scrollTopIsBottom) {
        value = order === "asc" ? scrollHeight - clientHeight : 0;
    } else {
        value =
            order === "asc"
                ? Number(threadScrollTop)
                : scrollHeight - Number(threadScrollTop) - clientHeight;
    }
    if (
        (lastSetValue !== undefined && Math.abs(lastSetValue - value) <= 1) ||
        isSmoothScrolling
    ) {
        return { type: "none" };
    }
    return {
        type: "restore",
        value,
        smooth:
            typeof threadScrollTop === "string" && threadScrollTop.includes("smooth"),
    };
}

export class ThreadScroll {
    /** @type {ReturnType<typeof useVisible>} */
    loadOlderState;
    /** @type {ReturnType<typeof useVisible>} */
    loadNewerState;
    /** @type {ReturnType<typeof awaitScrollEnd>|undefined} */
    smoothScrollingDeferred;
    isSmoothScrolling = false;

    /** @param {import("@mail/core/common/thread_scroll_hook").ThreadScrollOptions} options */
    constructor(options) {
        this.options = options;
        this.applyScroll = this.applyScroll.bind(this);
        this.saveScroll = this.saveScroll.bind(this);
        this.lastSetValue = undefined;
        this.loadedAndPatched = false;
        this.snapshot = undefined;
        this.newestPersistentMessage = undefined;
        this.oldestPersistentMessage = undefined;
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
        const thread = toRaw(this.options.getThread());
        this.options.applyScrollContextually(thread);
        this.snapshot = undefined;
        this.newestPersistentMessage = thread.newestPersistentMessage;
        this.oldestPersistentMessage = thread.oldestPersistentMessage;
        this.loadNewer = thread.loadNewer;
        if (!this.loadedAndPatched) {
            log.lifecycle("loadedAndPatched", () => ({ thread: thread.localId }));
            this.loadedAndPatched = true;
            this.loadOlderState.ready = true;
            this.loadNewerState.ready = true;
        }
    }

    /** @param {import("models").Thread} thread */
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
        if (action.type !== "none") {
            log.logic("scroll action", () => ({
                thread: thread.localId,
                ...action,
                threadScrollTop: thread.scrollTop,
                snapshot: this.snapshot,
            }));
        }
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
        log.lifecycle("reset", () => ({
            thread: toRaw(this.options.getThread())?.localId,
            loadedAndPatched: this.loadedAndPatched,
        }));
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
            this.smoothScrollingDeferred?.settle();
            const deferred = awaitScrollEnd({
                target: el,
                onSettle: () => {
                    log.logic("smooth scroll end", () => ({ value }));
                    if (this.smoothScrollingDeferred === deferred) {
                        this.smoothScrollingDeferred = undefined;
                        this.isSmoothScrolling = false;
                    }
                },
            });
            this.smoothScrollingDeferred = deferred;
            this.isSmoothScrolling = true;
            const { noMovement } = computeSmoothScrollTarget({
                value,
                scrollTop: el.scrollTop,
                scrollHeight: el.scrollHeight,
                clientHeight: el.clientHeight,
            });
            if (noMovement) {
                deferred.settle();
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
 * @property {{ el: HTMLElement|null }} scrollableRef
 * @property {() => import("models").Thread} getThread
 * @property {() => "asc"|"desc"} getOrder
 * @property {() => boolean} getMountedAndLoaded
 * @property {() => Object} getMessageHighlight
 * @property {() => number|undefined} getHighlightedMessageId
 * @property {(thread: import("models").Thread) => void} applyScrollContextually
 * @property {() => void} onReset
 * @property {() => void} onResize
 * @property {(ev: Event) => void} onScroll
 */
/**
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
                log.logic("load-older visible", () => ({
                    thread: toRaw(options.getThread()).localId,
                }));
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
                log.logic("load-newer visible", () => ({
                    thread: toRaw(options.getThread()).localId,
                }));
                toRaw(options.getThread()).fetchMoreMessages("newer");
            }
        },
        { ready: false },
    );
    let stopOnChange = Record.onChange(options.getThread(), "isLoaded", () => {
        if (!options.getThread().isLoaded || !options.getMountedAndLoaded()) {
            scroll.reset();
        }
    });
    onWillUpdateProps(
        /** @param {{thread: import("models").Thread}} nextProps */ (nextProps) => {
            if (nextProps.thread.notEq(options.getThread())) {
                stopOnChange();
                stopOnChange = Record.onChange(nextProps.thread, "isLoaded", () => {
                    if (!nextProps.thread.isLoaded || !options.getMountedAndLoaded()) {
                        scroll.reset();
                    }
                });
            }
        },
    );
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
    useEffect(scroll.applyScroll, () => {
        const thread = options.getThread();
        return [
            thread,
            thread.isLoaded,
            options.getMountedAndLoaded(),
            thread.messages.length,
            thread.newestPersistentMessage?.id,
            thread.oldestPersistentMessage?.id,
            thread.scrollTop,
            thread.loadNewer,
            options.getHighlightedMessageId(),
            options.getOrder(),
        ];
    });
    const observer = new ResizeObserver(() => {
        options.onResize();
        scroll.applyScroll();
    });
    useEffect(
        /**
         * @param {HTMLElement|null} el
         * @param {boolean} mountedAndLoaded
         */
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
