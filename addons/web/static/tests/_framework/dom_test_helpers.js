// @ts-check

import {
    advanceFrame,
    advanceTime,
    after,
    afterEach,
    animationFrame,
    check,
    clear,
    click,
    dblclick,
    drag,
    edit,
    fill,
    getActiveElement,
    hover,
    keyDown,
    keyUp,
    manuallyDispatchProgrammaticEvent,
    pointerDown,
    press,
    queryOne,
    queryRect,
    scroll,
    select,
    uncheck,
    waitFor,
} from "@odoo/hoot";
import { hasTouch } from "@web/core/browser/feature_detection";

/**
 * @typedef {import("@odoo/hoot").DragHelpers} DragHelpers
 * @typedef {import("@odoo/hoot").DragOptions} DragOptions
 * @typedef {import("@odoo/hoot").FillOptions} FillOptions
 * @typedef {import("@odoo/hoot").InputValue} InputValue
 * @typedef {import("@odoo/hoot").KeyStrokes} KeyStrokes
 * @typedef {import("@odoo/hoot").PointerOptions} PointerOptions
 * @typedef {import("@odoo/hoot").Position} Position
 * @typedef {import("@odoo/hoot").QueryOptions} QueryOptions
 * @typedef {import("@odoo/hoot").Target} Target
 * @typedef {DragOptions & {
 * initialPointerMoveDistance?: number;
 * pointerDownDuration?: number;
 * }} DragAndDropOptions
 * @typedef {{
 * altKey?: boolean;
 * ctrlKey?: boolean;
 * metaKey?: boolean;
 * shiftKey?: boolean;
 * }} KeyModifierOptions
 */

/**
 * @template T
 * @typedef {T | PromiseLike<T>} MaybePromise
 */

/**
 * @template {(...args: any) => any} T
 * @typedef {(...args: Parameters<T>) => MaybePromise<ReturnType<T>>} Promisify
 */

/**
 * @param {typeof click} clickFn
 * @param {Promise<Element>} nodePromise
 * @param {PointerOptions & KeyModifierOptions} [options]
 */
const callClick = async (clickFn, nodePromise, options) => {
    const actions = [() => clickFn(nodePromise, options)];
    if (options?.altKey) {
        actions.unshift(() => keyDown("Alt"));
        actions.push(() => keyUp("Alt"));
    }
    if (options?.ctrlKey) {
        actions.unshift(() => keyDown("Control"));
        actions.push(() => keyUp("Control"));
    }
    if (options?.metaKey) {
        actions.unshift(() => keyDown("Meta"));
        actions.push(() => keyUp("Meta"));
    }
    if (options?.shiftKey) {
        actions.unshift(() => keyDown("Shift"));
        actions.push(() => keyUp("Shift"));
    }

    for (const action of actions) {
        await action();
    }
    await animationFrame();
};

/**
 * @param {Node} node
 * @param {number} [distance]
 */
const dragForTolerance = async (node, distance) => {
    if (distance === 0) {
        return;
    }

    const position = {
        x: distance || 100,
        y: distance || 100,
    };
    await hover(node, { position, relative: true });
    await advanceFrame();
};

/**
 * @param {Node} node
 * @param {"dragenter" | "dragover" | "dragleave" | "drop"} type
 * @param {File[]} files
 */
const dispatchFileDragEvent = async (node, type, files) => {
    const dataTransfer = new DataTransfer();
    for (const file of files) {
        dataTransfer.items.add(file);
    }
    await manuallyDispatchProgrammaticEvent(node, type, { dataTransfer });
};

/**
 * @param {number} [delay]
 */
const waitForTouchDelay = async (delay) => {
    if (hasTouch()) {
        await advanceTime(delay || 500);
    }
};

/** @type {(() => any) | null} */
let cancelCurrentDragSequence = null;
/** @type {Target[]} */
const unconsumedContains = [];

afterEach(
    async () => {
        const cancelDragSequence = cancelCurrentDragSequence;
        cancelCurrentDragSequence = null;
        const targets = unconsumedContains.splice(0).map(String).join(", ");
        if (cancelDragSequence) {
            await cancelDragSequence();
        }
        if (targets) {
            throw new Error(
                `called 'contains' on "${targets}" without any action: use 'waitFor' if no interaction is intended`,
            );
        }
    },
    { global: true },
);

/**
 * @param {Target} target
 * @param {QueryOptions} [options]
 */
export function contains(target, options) {
    const consumeContains = () => {
        if (!consumed) {
            consumed = true;
            unconsumedContains.pop();
        }
    };

    const focusCurrent = async () => {
        const node = await nodePromise;
        if (node !== getActiveElement(node)) {
            await pointerDown(node);
        }
        return node;
    };

    let consumed = false;
    unconsumedContains.push(target);

    /** @type {Promise<Element>} */
    const nodePromise = waitFor.as("contains")(target, { visible: true, ...options });
    return {
        /**
         * @param {PointerOptions} [options]
         */
        check: async (options) => {
            consumeContains();
            await check(nodePromise, options);
            await animationFrame();
        },
        /**
         * @param {FillOptions} [options]
         */
        clear: async (options) => {
            consumeContains();
            await focusCurrent();
            await clear({ confirm: "auto", ...options });
            await animationFrame();
        },
        /**
         * @param {PointerOptions & KeyModifierOptions} [options]
         */
        click: async (options) => {
            consumeContains();
            await callClick(click, nodePromise, options);
        },
        /**
         * @param {PointerOptions & KeyModifierOptions} [options]
         */
        dblclick: async (options) => {
            consumeContains();
            await callClick(dblclick, nodePromise, options);
        },
        /**
         * @param {DragAndDropOptions} [options]
         * @returns {Promise<DragHelpers>}
         */
        drag: async (options) => {
            /** @type {any} */
            const cancelWithDelay = async (/** @type {any} */ options) => {
                await cancel(options);
                await advanceFrame();
                cancelCurrentDragSequence = null;
            };

            /** @type {any} */
            const dropWithDelay = async (
                /** @type {any} */ to,
                /** @type {any} */ options,
            ) => {
                if (to) {
                    await moveToWithDelay(to, options);
                }
                await drop();
                await advanceFrame();
                cancelCurrentDragSequence = null;
            };

            /** @type {typeof moveTo} */
            const moveToWithDelay = async (
                /** @type {any} */ to,
                /** @type {any} */ options,
            ) => {
                await moveTo(to, options);
                await advanceFrame();

                return helpersWithDelay;
            };

            consumeContains();

            await cancelCurrentDragSequence?.();

            const { cancel, drop, moveTo } = await drag(nodePromise, options);
            cancelCurrentDragSequence = cancelWithDelay;
            const helpersWithDelay = {
                cancel: cancelWithDelay,
                drop: dropWithDelay,
                moveTo: moveToWithDelay,
            };

            await waitForTouchDelay(options?.pointerDownDuration);

            await dragForTolerance(
                /** @type {any} */ (nodePromise),
                options?.initialPointerMoveDistance,
            );

            return helpersWithDelay;
        },
        /**
         * @param {Target} target
         * @param {DragAndDropOptions} [dropOptions]
         * @param {DragOptions} [dragOptions]
         */
        dragAndDrop: async (target, dropOptions, dragOptions) => {
            consumeContains();

            await cancelCurrentDragSequence?.();

            const [from, to] = await Promise.all([nodePromise, waitFor(target)]);
            const { drop, moveTo } = await drag(from, dragOptions);

            await waitForTouchDelay(dropOptions?.pointerDownDuration);

            await dragForTolerance(from, dropOptions?.initialPointerMoveDistance);

            await moveTo(to, dropOptions);
            await advanceFrame();

            await drop();
            await advanceFrame();
        },
        /**
         * @param {File[]} files
         */
        dragEnterFiles: async (files) => {
            consumeContains();
            await dispatchFileDragEvent(await nodePromise, "dragenter", files);
            await animationFrame();
        },
        /**
         * @param {File[]} files
         */
        dropFiles: async (files) => {
            consumeContains();
            await dispatchFileDragEvent(await nodePromise, "drop", files);
            await animationFrame();
        },
        /**
         * @param {InputValue} value
         * @param {FillOptions} [options]
         */
        edit: async (value, options) => {
            consumeContains();
            await focusCurrent();
            await edit(value, { confirm: "auto", ...options });
            await animationFrame();
        },
        /**
         * @param {InputValue} value
         * @param {FillOptions} [options]
         */
        fill: async (value, options) => {
            consumeContains();
            await focusCurrent();
            await fill(value, { confirm: "auto", ...options });
            await animationFrame();
        },
        focus: async () => {
            consumeContains();
            await focusCurrent();
            await animationFrame();
        },
        hover: async () => {
            consumeContains();
            await hover(nodePromise);
            await animationFrame();
        },
        /**
         * @param {KeyStrokes} keyStrokes
         * @param {KeyboardEventInit} [options]
         */
        keyDown: async (keyStrokes, options) => {
            consumeContains();
            await focusCurrent();
            await keyDown(keyStrokes, options);
            await animationFrame();
        },
        /**
         * @param {KeyStrokes} keyStrokes
         * @param {KeyboardEventInit} [options]
         */
        keyUp: async (keyStrokes, options) => {
            consumeContains();
            await focusCurrent();
            await keyUp(keyStrokes, options);
            await animationFrame();
        },
        /**
         * @param {KeyStrokes} keyStrokes
         * @param {KeyboardEventInit} [options]
         */
        press: async (keyStrokes, options) => {
            consumeContains();
            await focusCurrent();
            await press(keyStrokes, options);
            await animationFrame();
        },
        /**
         * @param {Position} position
         */
        scroll: async (position) => {
            consumeContains();
            await scroll(nodePromise, position, {
                scrollable: /** @type {any} */ (false),
                ...options,
            });
            await animationFrame();
        },
        /**
         * @param {InputValue} value
         */
        select: async (value) => {
            consumeContains();
            await select(/** @type {any} */ (value), { target: nodePromise });
            await animationFrame();
        },
        /**
         * @param {InputValue} value
         */
        selectDropdownItem: async (value) => {
            consumeContains();
            await callClick(
                click,
                /** @type {any} */ (
                    queryOne(".dropdown-toggle", {
                        root: /** @type {HTMLElement} */ (await nodePromise),
                    })
                ),
            );
            const item = await waitFor(`.dropdown-item:contains(${value})`);
            await callClick(click, /** @type {any} */ (item));
            await animationFrame();
        },
        /**
         * @param {PointerOptions} [options]
         */
        uncheck: async (options) => {
            consumeContains();
            await uncheck(nodePromise, options);
            await animationFrame();
        },
    };
}

/**
 * @param {string} style
 */
export function defineStyle(style) {
    const styleEl = document.createElement("style");
    styleEl.textContent = style;

    document.head.appendChild(styleEl);
    after(() => styleEl.remove());
}

/**
 * @param {string} value
 */
export async function editAce(value) {
    await manuallyDispatchProgrammaticEvent(
        queryOne(".ace_editor .ace_content"),
        "mousedown",
    );

    await contains(".ace_editor textarea", { displayed: true, visible: false }).edit(
        value,
        {
            instantly: true,
        },
    );
}

/**
 * @param {Target} from
 * @param {DragAndDropOptions} [options]
 */
export async function sortableDrag(from, options) {
    const fromRect = queryRect(from);
    const { cancel, drop, moveTo } = await contains(from).drag({
        initialPointerMoveDistance: 0,
        ...options,
    });

    let isFirstMove = true;

    /**
     * @param {string} [targetSelector]
     */
    const moveAbove = async (targetSelector) => {
        await moveTo(targetSelector, {
            position: {
                x: fromRect.x - queryRect(targetSelector).x + fromRect.width / 2,
                y: fromRect.height / 2 + 5,
            },
            relative: true,
        });
        isFirstMove = false;
    };

    /**
     * @param {string} [targetSelector]
     */
    const moveUnder = async (targetSelector) => {
        const elRect = queryRect(targetSelector);
        const firstMoveBelow = isFirstMove && elRect.y > fromRect.y;
        await moveTo(targetSelector, {
            position: {
                x: fromRect.x - elRect.x + fromRect.width / 2,
                y:
                    ((firstMoveBelow ? -1 : 1) * fromRect.height) / 2 +
                    elRect.height +
                    (firstMoveBelow ? 4 : -1),
            },
            relative: true,
        });
        isFirstMove = false;
    };

    return { cancel, moveAbove, moveTo, moveUnder, drop };
}
