/** @odoo-module native */
import { monitorAudio } from "@mail/utils/common/media_monitoring";
import { onChange } from "@mail/utils/common/misc";
import {
    Component,
    onMounted,
    onPatched,
    onWillDestroy,
    onWillUnmount,
    toRaw,
    useComponent,
    useEffect,
    useRef,
    useState,
    useSubEnv,
    xml,
} from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/translation";
import { Deferred } from "@web/core/utils/concurrency";
import { makeDraggableHook } from "@web/core/utils/dnd";
import { useService } from "@web/core/utils/hooks";
import { OVERLAY_SYMBOL } from "@web/ui/overlay/overlay_container";
/**
 * @param {() => EventTarget|undefined} target
 * @param {string} eventName
 * @param {(ev: Event) => void} handler
 * @param {boolean|AddEventListenerOptions} [eventParams]
 */
function useLazyExternalListener(target, eventName, handler, eventParams) {
    const boundHandler = handler.bind(useComponent());
    /** @type {EventTarget|undefined} */
    let t;
    onMounted(() => {
        t = target();
        if (!t) {
            return;
        }
        t.addEventListener(eventName, boundHandler, eventParams);
    });
    onPatched(() => {
        const t2 = target();
        if (t !== t2) {
            if (t) {
                t.removeEventListener(eventName, boundHandler, eventParams);
            }
            if (t2) {
                t2.addEventListener(eventName, boundHandler, eventParams);
            }
            t = t2;
        }
    });
    onWillUnmount(() => {
        if (!t) {
            return;
        }
        t.removeEventListener(eventName, boundHandler, eventParams);
    });
}

/**
 * @param {Object} target
 * @param {string|string[]} key
 * @param {Function} callback
 */
export function useOnChange(target, key, callback) {
    const dispose = onChange(target, key, callback);
    onWillDestroy(dispose);
    return dispose;
}

/**
 * @param {string} refName
 * @param {(ev: MouseEvent, targets: {downTarget: EventTarget, upTarget: EventTarget}) => void} cb
 */
export function onExternalClick(refName, cb) {
    /** @type {EventTarget|null} */
    let downTarget;
    /** @type {EventTarget|null} */
    let upTarget;
    const ref = useRef(refName);
    /** @param {MouseEvent} ev */
    function onClick(ev) {
        if (ref.el && !ref.el.contains(/** @type {Node} */ (ev.composedPath()[0]))) {
            cb(ev, { downTarget, upTarget });
            upTarget = downTarget = null;
        }
    }
    /** @param {MouseEvent} ev */
    function onMousedown(ev) {
        downTarget = ev.target;
    }
    /** @param {MouseEvent} ev */
    function onMouseup(ev) {
        upTarget = ev.target;
    }
    onMounted(() => {
        document.body.addEventListener("mousedown", onMousedown, true);
        document.body.addEventListener("mouseup", onMouseup, true);
        document.body.addEventListener("click", onClick, true);
    });
    onWillUnmount(() => {
        document.body.removeEventListener("mousedown", onMousedown, true);
        document.body.removeEventListener("mouseup", onMouseup, true);
        document.body.removeEventListener("click", onClick, true);
    });
}

/**
 * @typedef {Object} HoverTarget
 * @property {{el: HTMLElement|null}} ref
 */

/**
 * @param {HoverTarget[]} rawTargets
 * @param {EventTarget|null} node
 * @returns {HoverTarget|null}
 */
function hoverTargetContaining(rawTargets, node) {
    for (const target of rawTargets) {
        if (target.ref.el?.contains(/** @type {Node} */ (node))) {
            return target;
        }
    }
    return null;
}
/**
 * @param {((target: EventTarget|null) => boolean)[]} containsFns
 * @param {EventTarget|null} node
 * @returns {boolean}
 */
function overlayContaining(containsFns, node) {
    return containsFns.some((contains) => contains(node));
}
/**
 * @param {string|string[]|Function|Function[]} refNames
 * @returns {HoverTarget[]}
 */
/**
 * @param {any} state
 * @param {Object} callbacks
 * @param {() => void} [callbacks.onHover]
 * @param {() => void} [callbacks.onAway]
 * @param {[number, () => void]} [callbacks.onHovering]
 * @returns {{setHover: (hovering: boolean) => void, clearTimers: () => void}}
 */
function makeHoverSwitch(state, { onHover, onAway, onHovering }) {
    let wasHovering = false;
    /** @type {ReturnType<typeof setTimeout>} */
    let hoveringTimeout;
    /** @type {ReturnType<typeof setTimeout>} */
    let awayTimeout;
    return {
        /** @param {boolean} hovering */
        setHover(hovering) {
            if (hovering && !wasHovering) {
                state.isHover = true;
                clearTimeout(awayTimeout);
                clearTimeout(hoveringTimeout);
                if (typeof onHover === "function") {
                    onHover();
                }
                if (Array.isArray(onHovering)) {
                    const [delay, cb] = onHovering;
                    hoveringTimeout = setTimeout(() => {
                        cb();
                    }, delay);
                }
            } else if (!hovering) {
                state.isHover = false;
                clearTimeout(awayTimeout);
                clearTimeout(hoveringTimeout);
                if (typeof onAway === "function") {
                    awayTimeout = setTimeout(() => {
                        onAway();
                    }, 100);
                }
            }
            wasHovering = hovering;
        },
        clearTimers() {
            clearTimeout(hoveringTimeout);
            clearTimeout(awayTimeout);
        },
    };
}
function useHoverTargets(refNames) {
    const refNameList = Array.isArray(refNames) ? refNames : [refNames];
    /** @type {HoverTarget[]} */
    const targets = [];
    for (const refName of refNameList) {
        targets.push({
            ref: typeof refName === "function" ? refName : useRef(refName),
        });
    }
    return targets;
}
/**
 * @param {HoverTarget[]} targets
 * @param {(ev: MouseEvent) => void} onEnter
 * @param {(ev: MouseEvent) => void} onLeave
 */
function makeHoverState(targets, onEnter, onLeave) {
    const state = useState({
        /** @param {boolean} newIsHover */
        set isHover(newIsHover) {
            if (this._isHover !== newIsHover) {
                this._isHover = newIsHover;
                this._count++;
            }
        },
        get isHover() {
            void this._count;
            return this._isHover;
        },
        _contains: /** @type {((target: EventTarget|null) => boolean)[]} */ ([]),
        _count: 0,
        _isHover: false,
        _targets: targets,
        /**
         * @param {HoverTarget} target
         * @returns {() => void}
         */
        addTarget(target) {
            state._targets.push(target);
            const handleMouseenter = (/** @type {MouseEvent} */ ev) => onEnter(ev);
            const handleMouseleave = (/** @type {MouseEvent} */ ev) => onLeave(ev);
            target.ref.el.addEventListener("mouseenter", handleMouseenter, true);
            target.ref.el.addEventListener("mouseleave", handleMouseleave, true);
            return () => {
                target.ref.el.removeEventListener("mouseenter", handleMouseenter, true);
                target.ref.el.removeEventListener("mouseleave", handleMouseleave, true);
                const idx = state._targets.indexOf(target);
                if (idx !== -1) {
                    state._targets.splice(idx, 1);
                }
            };
        },
    });
    return state;
}
/**
 * @param {HoverTarget[]} targets
 * @param {(ev: MouseEvent) => void} onEnter
 * @param {(ev: MouseEvent) => void} onLeave
 */
function bindHoverListeners(targets, onEnter, onLeave) {
    for (const target of targets) {
        useLazyExternalListener(
            () => target.ref.el,
            "mouseenter",
            (ev) => onEnter(/** @type {MouseEvent} */ (ev)),
            true,
        );
        useLazyExternalListener(
            () => target.ref.el,
            "mouseleave",
            (ev) => onLeave(/** @type {MouseEvent} */ (ev)),
            true,
        );
    }
}
/**
 * @param {string | string[] | Function} refNames
 * @param {Object} param1
 * @param {() => void} [param1.onHover]
 * @param {() => void} [param1.onAway]
 * @param {[number, () => void]} [param1.onHovering]
 * @param {() => any[]} [param1.stateObserver]
 * @returns {({ isHover: boolean })}
 */
export function useHover(
    refNames,
    { onHover, onAway, stateObserver, onHovering } = {},
) {
    const targets = useHoverTargets(refNames);
    /** @type {HoverTarget|null} */
    let lastHoveredTarget;
    const state = makeHoverState(
        targets,
        (ev) => onmouseenter(ev),
        (ev) => onmouseleave(ev),
    );
    const { setHover, clearTimers } = makeHoverSwitch(state, {
        onHover,
        onAway,
        onHovering,
    });
    /** @param {MouseEvent} ev */
    function onmouseenter(ev) {
        if (state.isHover) {
            return;
        }
        const rawState = toRaw(state);
        const target = hoverTargetContaining(rawState._targets, ev.target);
        if (target) {
            setHover(true);
            lastHoveredTarget = target;
            return;
        }
        if (overlayContaining(rawState._contains, ev.target)) {
            setHover(true);
        }
    }
    /** @param {MouseEvent} ev */
    function onmouseleave(ev) {
        if (!state.isHover) {
            return;
        }
        const rawState = toRaw(state);
        if (hoverTargetContaining(rawState._targets, ev.relatedTarget)) {
            return;
        }
        if (overlayContaining(rawState._contains, ev.relatedTarget)) {
            return;
        }
        setHover(false);
        lastHoveredTarget = null;
    }
    onWillUnmount(clearTimers);
    bindHoverListeners(targets, onmouseenter, onmouseleave);
    if (stateObserver) {
        useEffect(
            /** @param {any} open */ (open) => {
                if ((lastHoveredTarget && !lastHoveredTarget.ref.el) || !open) {
                    setHover(false);
                    lastHoveredTarget = null;
                }
            },
            stateObserver,
        );
    }
    return state;
}

export class UseHoverOverlay extends Component {
    static props = ["slots", "hover"];
    static template = xml`<div t-ref="root"><t t-slot="default"/></div>`;

    setup() {
        super.setup();
        this.root = useRef("root");
        const overlayContains = toRaw(
            /** @type {Record<symbol, {contains: (target: EventTarget|null) => boolean}>} */ (
                this.env
            )[OVERLAY_SYMBOL].contains,
        );
        /** @type {(() => void)|undefined} */
        let removeTarget;
        onMounted(() => {
            this.props.hover._contains.push(overlayContains);
            removeTarget = this.props.hover.addTarget({
                ref: { el: this.root.el.closest(".o-overlay-item") },
            });
        });
        onWillUnmount(() => {
            const idx = this.props.hover._contains.indexOf(overlayContains);
            if (idx !== -1) {
                this.props.hover._contains.splice(idx, 1);
            }
            removeTarget?.();
        });
    }
}

/**
 * @param {string} refName
 * @param {function} callback
 * @param {number} threshold
 */
export function useOnBottomScrolled(refName, callback, threshold = 1) {
    const ref = useRef(refName);
    function onScroll() {
        if (
            Math.abs(ref.el.scrollTop + ref.el.clientHeight - ref.el.scrollHeight) <
            threshold
        ) {
            callback();
        }
    }
    useLazyExternalListener(() => ref.el, "scroll", onScroll);
}

/**
 * @param {string} refName
 * @param {(isVisible: boolean|undefined) => void} [cb]
 * @param {Object} [options]
 * @param {boolean} [options.ready=true]
 * @returns {{isVisible: boolean|undefined, ready: boolean}}
 */
export function useVisible(refName, cb, { ready = true } = {}) {
    const ref = useRef(refName);
    const state = useState({
        isVisible: undefined,
        ready,
    });
    /** @param {boolean|undefined} value */
    function setValue(value) {
        state.isVisible = value;
        cb?.(state.isVisible);
    }
    const observer = new IntersectionObserver(
        /** @param {IntersectionObserverEntry[]} entries */
        (entries) => {
            setValue(entries.at(-1).isIntersecting);
        },
    );
    useEffect(
        /**
         * @param {HTMLElement|null} el
         * @param {boolean} ready
         */
        (el, ready) => {
            if (el && ready) {
                observer.observe(el);
                return () => {
                    setValue(undefined);
                    observer.unobserve(el);
                };
            }
        },
        () => [ref.el, state.ready],
    );
    onWillUnmount(() => observer.disconnect());
    return state;
}

/**
 * @typedef {Object} MessageScrolling
 * @property {function} clear
 * @property {function} highlightMessage
 * @property {number|null} highlightedMessageId
 */

/**
 * @param {number} [duration=2000]
 * @returns {MessageScrolling}
 */
export function useMessageScrolling(duration = 2000) {
    /** @type {ReturnType<typeof browser.setTimeout>|null} */
    let timeout;
    const state = useState({
        clear() {
            if (this.highlightedMessageId) {
                browser.clearTimeout(timeout);
                timeout = null;
                this.highlightedMessageId = null;
            }
        },
        /**
         * @param {import("models").Message} message
         * @param {import("models").Thread} thread
         */
        async highlightMessage(message, thread) {
            state.initiated = true;
            let messageScrollDirection;
            if (message.notIn(thread.messages)) {
                messageScrollDirection =
                    message.id < thread.messages[0]?.id ? "top" : "bottom";
                await thread.loadAround(message.id);
            }
            const lastHighlightedMessageId = state.highlightedMessageId;
            this.clear();
            if (lastHighlightedMessageId === message.id) {
                await new Promise((resolve) => browser.setTimeout(resolve));
            }
            thread.scrollTop = messageScrollDirection === "top" ? "bottom" : undefined;
            if (thread.scrollTop === "bottom") {
                state.startupDeferred = new Deferred();
                await state.startupDeferred;
                state.startupDeferred = null;
            }
            state.highlightedMessageId = message.id;
            state.initiated = false;
            timeout = browser.setTimeout(() => this.clear(), duration);
        },
        initiated: false,
        startupDeferred: null,
        scrollPromise: null,
        /** @param {Element} el */
        scrollTo(el) {
            state.scrollPromise?.resolve();
            const scrollPromise = new Deferred();
            state.scrollPromise = scrollPromise;
            /** @type {ReturnType<typeof browser.setTimeout>} */
            let scrollTimeout;
            const onScrollEnd = () => {
                browser.clearTimeout(scrollTimeout);
                document.removeEventListener("scrollend", onScrollEnd, {
                    capture: true,
                });
                scrollPromise.resolve();
            };
            if ("onscrollend" in window) {
                document.addEventListener("scrollend", onScrollEnd, {
                    capture: true,
                    once: true,
                });
                scrollTimeout = browser.setTimeout(onScrollEnd, 3000);
            } else {
                scrollTimeout = browser.setTimeout(onScrollEnd, 250);
            }
            el.scrollIntoView({ behavior: "smooth", block: "center" });
            return scrollPromise;
        },
        highlightedMessageId: null,
    });
    onWillUnmount(() => {
        browser.clearTimeout(timeout);
        timeout = null;
        state.startupDeferred?.resolve();
        state.scrollPromise?.resolve();
    });
    return state;
}

export function useMicrophoneVolume() {
    let isClosed = false;
    /** @type {MediaStreamTrack|null} */
    let audioTrack = null;
    /** @type {(() => void)|undefined} */
    let disconnectAudioMonitor;
    /** @type {Promise<() => void>|undefined} */
    let audioMonitorPromise;
    const store = useService("mail.store");
    const state = useState({
        isReady: true,
        isActive: false,
        value: 0,
        toggle: async () => {
            if (!state.isReady) {
                return;
            }
            state.isReady = false;
            disconnectAudioMonitor?.();
            disconnectAudioMonitor = undefined;
            if (audioTrack) {
                audioTrack.stop();
                audioTrack = null;
                state.isReady = true;
                state.isActive = false;
                state.value = 0;
                return;
            }
            let track;
            try {
                try {
                    const audioStream =
                        await browser.navigator.mediaDevices.getUserMedia({
                            audio: store.settings.audioConstraints,
                        });
                    track = audioStream.getAudioTracks()[0];
                } catch {
                    store.env.services.notification.add(
                        _t('"%(hostname)s" requires microphone access', {
                            hostname: browser.location.host,
                        }),
                        { type: "warning" },
                    );
                    return;
                }
                if (isClosed) {
                    track.stop();
                    return;
                }
                audioMonitorPromise = monitorAudio(track, {
                    onTic: /** @param {number} value */ (value) => {
                        state.value = value;
                    },
                    processInterval: 100,
                });
                disconnectAudioMonitor = await audioMonitorPromise;
                audioTrack = track;
                state.isActive = true;
            } catch {
                track?.stop();
            } finally {
                state.isReady = true;
            }
        },
    });
    onWillUnmount(async () => {
        isClosed = true;
        try {
            await audioMonitorPromise;
        } catch {}
        audioTrack?.stop();
        disconnectAudioMonitor?.();
    });
    return state;
}

/**
 * @param {Object} options
 * @param {string} options.refName
 * @param {{start: number, end: number, direction: "forward"|"backward"|"none"}} options.model
 * @param {(ev: MouseEvent) => boolean|Promise<boolean>} [options.preserveOnClickAwayPredicate]
 * @returns {{restore: () => void, moveCursor: (position: number) => void}}
 */
export function useSelection({
    refName,
    model,
    preserveOnClickAwayPredicate = () => false,
}) {
    const ui = useService("ui");
    const ref = /** @type {{el: HTMLInputElement|HTMLTextAreaElement|null}} */ (
        useRef(refName)
    );
    function onSelectionChange() {
        const activeElement = /** @type {Document|ShadowRoot} */ (ref.el?.getRootNode())
            ?.activeElement;
        if (activeElement && activeElement === ref.el) {
            Object.assign(model, {
                start: ref.el.selectionStart,
                end: ref.el.selectionEnd,
                direction: ref.el.selectionDirection,
            });
        }
    }
    onExternalClick(
        refName,
        /** @param {MouseEvent} ev */ async (ev) => {
            if (await preserveOnClickAwayPredicate(ev)) {
                return;
            }
            if (!ref.el) {
                return;
            }
            Object.assign(model, {
                start: ref.el.value.length,
                end: ref.el.value.length,
                direction: ref.el.selectionDirection,
            });
        },
    );
    onMounted(() => {
        document.addEventListener("selectionchange", onSelectionChange);
        document.addEventListener("input", onSelectionChange);
    });
    onWillUnmount(() => {
        document.removeEventListener("selectionchange", onSelectionChange);
        document.removeEventListener("input", onSelectionChange);
    });
    return {
        restore() {
            ref.el?.setSelectionRange(model.start, model.end, model.direction);
        },
        /** @param {number} position */
        moveCursor(position) {
            model.start = model.end = position;
            if (ref.el && !ui.isSmall) {
                ref.el.selectionStart = ref.el.selectionEnd = position;
            }
        },
    };
}

/**
 * @param {{isOpen: boolean}} [dropdownState]
 * @returns {{class: string, contentClass: string, menuClass: string}}
 */
export function useDiscussSystray(dropdownState) {
    const ui = useService("ui");
    if (dropdownState) {
        useEffect(
            /** @param {boolean} isOpen */
            (isOpen) => {
                if (isOpen) {
                    document.body.classList.add("o-mail-discuss-systray-menu-open");
                    return () => {
                        document.body.classList.remove(
                            "o-mail-discuss-systray-menu-open",
                        );
                    };
                }
            },
            () => [dropdownState.isOpen],
        );
    }
    return {
        class: "o-mail-DiscussSystray-class",
        get contentClass() {
            return `d-flex flex-column flex-grow-1 ${
                ui.isSmall ? "overflow-auto o-scrollbar-thin w-100 mh-100" : ""
            }`;
        },
        get menuClass() {
            return `p-0 o-mail-DiscussSystray ${
                ui.isSmall
                    ? "o-mail-systrayFullscreenDropdownMenu start-0 w-100 mh-100 d-flex flex-column mt-0 border-0 shadow-lg"
                    : ""
            }`;
        },
    };
}

export const useMovable = makeDraggableHook({
    name: "useMovable",
    /** @param {import("@web/core/utils/dnd/draggable_hook_builder").DraggableBuildHandlerParams} params */
    onWillStartDrag({ ctx, addCleanup, addStyle, getRect }) {
        ctx.current.container = document.createElement("div");
        addStyle(ctx.current.container, {
            position: "fixed",
            top: 0,
            bottom: 0,
            left: 0,
            right: 0,
        });
        ctx.current.element.after(ctx.current.container);
        addCleanup(() => ctx.current.container.remove());
    },
    onDragStart: () => true,
    onDragEnd: () => true,
    /**
     * @param {import("@web/core/utils/dnd/draggable_hook_builder").DraggableBuildHandlerParams} params
     * @returns {{top: number, left: number}}
     */
    onDrop({ ctx, getRect }) {
        const { top, left } = getRect(ctx.current.element);
        return { top, left };
    },
});

export const LONG_PRESS_DELAY = 400;

/**
 * @param {string} refName
 * @param {Object} options
 * @param {() => void} [options.action]
 * @param {() => boolean} [options.predicate]
 */
export function useLongPress(refName, { action, predicate = () => true } = {}) {
    const MOVE_TRESHOLD = 10;
    const ref = useRef(refName);
    /** @type {ReturnType<typeof setTimeout>|null} */
    let timer = null;
    let startX = 0;
    let startY = 0;

    function reset() {
        clearTimeout(timer);
        timer = null;
    }
    onWillUnmount(reset);
    useLazyExternalListener(
        () => ref.el,
        "touchstart",
        (ev) => {
            if (!predicate()) {
                return;
            }
            const touch = /** @type {TouchEvent} */ (ev).touches[0];
            startX = touch.clientX;
            startY = touch.clientY;
            timer = setTimeout(() => {
                action();
                reset();
            }, LONG_PRESS_DELAY);
        },
    );
    useLazyExternalListener(
        () => ref.el,
        "touchmove",
        (ev) => {
            if (!timer) {
                return;
            }
            const touch = /** @type {TouchEvent} */ (ev).touches[0];
            const dx = touch.clientX - startX;
            const dy = touch.clientY - startY;
            if (Math.hypot(dx, dy) > MOVE_TRESHOLD) {
                reset();
            }
        },
    );
    useLazyExternalListener(() => ref.el, "touchend", reset);
    useLazyExternalListener(() => ref.el, "touchcancel", reset);
}

export const inDiscussCallViewProps = ["isPip?"];
export function useInDiscussCallView() {
    const component = useComponent();
    useSubEnv({
        inDiscussCallView: {
            get isPip() {
                return component.props.isPip;
            },
        },
    });
}
