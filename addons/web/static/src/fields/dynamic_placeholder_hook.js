// @ts-check
/** @odoo-module native */

import { useComponent } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { usePopover } from "@web/ui/popover/popover_hook";

import { DynamicPlaceholderPopover } from "./dynamic_placeholder_popover.js";
import {
    buildInlinePlaceholder,
    placeholderExpression,
    resolveTzPath,
} from "./dynamic_placeholder_syntax.js";

const TRIGGER_KEY = "#";

/**
 * @param {import("@web/core/network/orm_service").ORM} orm
 * @param {string} model
 * @param {{ path: string, defaultValue?: string, fieldType?: string }} spec
 * @returns {Promise<string>} the text to splice in, leading space included
 */
async function buildPlaceholderText(orm, model, { path, defaultValue, fieldType }) {
    const tzPath =
        fieldType === "datetime"
            ? ((await resolveTzPath(orm, model)) ?? undefined)
            : undefined;
    return ` ${buildInlinePlaceholder({ path, fieldType, defaultValue, tzPath })}`;
}

/**
 * Splices `text` into the element at `rangeIndex`, optionally swallowing the
 * `#` that opened the picker, and tells the input hook about it.
 *
 * @param {HTMLInputElement | HTMLTextAreaElement} element
 * @param {string} text
 * @param {{ rangeIndex: number, removeTriggerKey: boolean }} where
 */
function insertAtRange(element, text, { rangeIndex, removeTriggerKey }) {
    element.focus();
    let start = rangeIndex;
    if (removeTriggerKey && element.value[rangeIndex - 1] === TRIGGER_KEY) {
        start -= 1;
    }
    element.setRangeText(text, start, rangeIndex, "end");
    element.dispatchEvent(new InputEvent("input"));
}

export function useDynamicPlaceholder(/** @type {any} */ elementRef) {
    const ownerField = useComponent();
    /** @type {Function | undefined} */
    let closeCallback;
    const popover = usePopover(DynamicPlaceholderPopover, {
        onClose: () => closeCallback?.(),
    });
    const notification = useService("notification");
    const orm = useService("orm");

    /** @type {any} */
    let model = null;
    /** @type {any} */
    let pendingRangeIndex = null;

    /**
     * @param {string} path
     * @param {string} [defaultValue]
     * @param {Object} [options]
     * @param {string} [options.fieldType]
     * @param {number} [options.rangeIndex]
     * @param {boolean} [options.removeTriggerKey]
     */
    const insert = async function (
        path,
        defaultValue,
        { fieldType, rangeIndex = 0, removeTriggerKey = false } = {},
    ) {
        const element = elementRef?.el;
        if (!element || !path) {
            return;
        }
        const text = await buildPlaceholderText(orm, model, {
            path,
            defaultValue,
            fieldType,
        });
        insertAtRange(element, text, { rangeIndex, removeTriggerKey });
    };

    const onDynamicPlaceholderValidate = function (path, defaultValue, fieldType) {
        const rangeIndex = pendingRangeIndex;
        pendingRangeIndex = null;
        if (path && rangeIndex !== null) {
            return insert(path, defaultValue, {
                fieldType,
                rangeIndex,
                removeTriggerKey: true,
            });
        }
    };
    const onDynamicPlaceholderClose = function () {
        elementRef?.el?.focus();
    };

    /**
     * @public
     * @param {Object} opts
     * @param {function} opts.validateCallback
     * @param {function} [opts.closeCallback]
     */
    function open(opts) {
        if (!model) {
            return notification.add(
                _t(
                    "You need to select a model before opening the dynamic placeholder selector.",
                ),
                { type: "danger" },
            );
        }
        closeCallback = opts.closeCallback;
        popover.open(elementRef?.el, {
            resModel: model,
            validate: opts.validateCallback,
            plainText: true,
            expressionFor: (path, fieldDef) =>
                placeholderExpression(path, { fieldType: fieldDef?.type }),
        });
    }
    function onKeydown(ev) {
        const element = elementRef?.el;
        if (ev.target === element && ev.key === TRIGGER_KEY) {
            pendingRangeIndex = element.selectionStart + 1;
            open({
                validateCallback: onDynamicPlaceholderValidate,
                closeCallback: onDynamicPlaceholderClose,
            });
        }
    }
    function updateModel(modelNameLocation) {
        const recordData = ownerField.props.record.data;
        model =
            (modelNameLocation && recordData[modelNameLocation]) ||
            recordData.render_model ||
            recordData.model;
    }

    return {
        updateModel: updateModel,
        onKeydown: onKeydown,
        insert: insert,
        open: open,
    };
}
