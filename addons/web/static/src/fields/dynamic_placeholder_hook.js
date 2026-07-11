// @ts-check
/** @odoo-module native */

/** @module @web/fields/dynamic_placeholder_hook - OWL hook that opens a dynamic placeholder popover on trigger key */

import { useComponent } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
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
     * Single insertion routine, shared by the trigger-key path (which removes
     * the typed trigger key) and the magic-wand button path. Always goes
     * through the synthetic-event path so `useInputField` stays the single
     * source of dirty truth (the record is committed on blur/Tab, not here).
     *
     * @param {string} path field chain (e.g. "partner_id.name")
     * @param {string} [defaultValue] fallback when the placeholder is empty
     * @param {Object} [options]
     * @param {number} [options.rangeIndex] caret index to insert at
     * @param {boolean} [options.removeTriggerKey] replace the trigger key
     *     just before ``rangeIndex`` instead of inserting after it
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
        // Synthetic events so useInputField marks the field dirty.
        element.dispatchEvent(new InputEvent("input"));
        element.dispatchEvent(new KeyboardEvent("keydown"));
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
        // When the user cancel/close the popover, the path is empty.
        if (path) {
            insert(path, defaultValue, { rangeIndex, removeTriggerKey: true });
        }
    };
    const onDynamicPlaceholderClose = function () {
        elementRef?.el.focus();
    };

    /**
     * Open a Model Field Selector to build a dynamic placeholder string,
     * with or without a default value.
     *
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
            // +1 to take the trigger key char into account
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
