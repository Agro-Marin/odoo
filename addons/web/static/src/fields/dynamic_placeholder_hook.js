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

export function useDynamicPlaceholder(elementRef) {
    const ownerField = useComponent();
    let closeCallback;
    const popover = usePopover(DynamicPlaceholderPopover, {
        onClose: () => closeCallback?.(),
    });
    const notification = useService("notification");
    const orm = useService("orm");

    let model = null;
    // Where the placeholder goes once the popover comes back. Kept here rather
    // than on the input: the two closures that need it are both in this hook,
    // and a DOM attribute is not a variable.
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
        // The type table lives in the syntax module so that a subject and a
        // body format the same field the same way.
        const tzPath =
            fieldType === "datetime" ? await resolveTzPath(orm, model) : undefined;
        const dynamicPlaceholder = ` ${buildInlinePlaceholder({
            path,
            fieldType,
            defaultValue,
            tzPath,
        })}`;
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
            // A char or text field shows markup as tags, and the server judges
            // the expression this hook will write, not the bare path.
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
        // `render_model` is the server's own answer to "which model do these
        // placeholders resolve against", computed per model by
        // `mixin.mail.render._compute_render_model`. A view may still name a
        // field explicitly -- `sms.composer` is not a render mixin and has no
        // `render_model` -- and that declaration wins.
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
