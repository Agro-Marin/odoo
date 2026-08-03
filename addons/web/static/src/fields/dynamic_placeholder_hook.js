// @ts-check
/** @odoo-module native */

/** @module @web/fields/dynamic_placeholder_hook */

import { useComponent } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { usePopover } from "@web/ui/popover/popover_hook";

import { DynamicPlaceholderPopover } from "./dynamic_placeholder_popover.js";

export function useDynamicPlaceholder(elementRef) {
    const TRIGGER_KEY = "#";
    const ownerField = useComponent();
    let closeCallback;
    let positionCallback;
    const popover = usePopover(DynamicPlaceholderPopover, {
        onClose: () => closeCallback?.(),
        onPositioned: (popper, position) => positionCallback?.(popper, position),
    });
    const notification = useService("notification");

    let model = null;

    /**
     * @param {string} path
     * @param {string} [defaultValue]
     * @param {Object} [options]
     * @param {number} [options.rangeIndex]
     * @param {boolean} [options.removeTriggerKey]
     */
    const insert = function (
        path,
        defaultValue,
        { rangeIndex = 0, removeTriggerKey = false } = {},
    ) {
        const element = elementRef?.el;
        if (!element || !path) {
            return;
        }
        defaultValue = (defaultValue || "").replace("|||", "");
        const dynamicPlaceholder = ` {{object.${path}${
            defaultValue.length ? ` ||| ${defaultValue}` : ""
        }}}`;
        element.focus();
        let start = rangeIndex;
        if (removeTriggerKey && element.value[rangeIndex - 1] === TRIGGER_KEY) {
            start -= 1;
        }
        element.setRangeText(dynamicPlaceholder, start, rangeIndex, "end");
        // A synthetic KeyboardEvent carries no `key`, so getActiveHotkey()
        // returns "" and every branch in useInputField's keydown handler
        // misses: dispatching one only looked like it committed the change.
        element.dispatchEvent(new InputEvent("input"));
    };

    const onDynamicPlaceholderValidate = function (path, defaultValue) {
        const element = elementRef?.el;
        if (!element) {
            return;
        }
        const rangeIndex = Number.parseInt(
            element.getAttribute("data-oe-dynamic-placeholder-range-index"),
            10,
        );
        element.removeAttribute("data-oe-dynamic-placeholder-range-index");
        if (path) {
            insert(path, defaultValue, { rangeIndex, removeTriggerKey: true });
        }
    };
    const onDynamicPlaceholderClose = function () {
        elementRef?.el?.focus();
    };

    /**
     * @public
     * @param {Object} opts
     * @param {function} opts.validateCallback
     * @param {function} opts.closeCallback
     * @param {function} [opts.positionCallback]
     */
    async function open(opts) {
        if (!model) {
            return notification.add(
                _t(
                    "You need to select a model before opening the dynamic placeholder selector.",
                ),
                { type: "danger" },
            );
        }
        closeCallback = opts.closeCallback;
        positionCallback = opts.positionCallback;
        popover.open(elementRef?.el, {
            resModel: model,
            validate: opts.validateCallback,
        });
    }
    async function onKeydown(ev) {
        const element = elementRef?.el;
        if (ev.target === element && ev.key === TRIGGER_KEY) {
            const currentRangeIndex = element.selectionStart;
            element.setAttribute(
                "data-oe-dynamic-placeholder-range-index",
                currentRangeIndex + 1,
            );
            await open({
                validateCallback: onDynamicPlaceholderValidate,
                closeCallback: onDynamicPlaceholderClose,
            });
        }
    }
    function updateModel(model_name_location) {
        const recordData = ownerField.props.record.data;
        model = recordData[model_name_location] || recordData.model;
    }

    return {
        updateModel: updateModel,
        onKeydown: onKeydown,
        insert: insert,
        setElementRef: (er) => (elementRef = er),
        open: open,
    };
}
