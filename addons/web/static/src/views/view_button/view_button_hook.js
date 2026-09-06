// @ts-check
/** @odoo-module native */

import { status, useComponent, useEnv, useSubEnv } from "@odoo/owl";
import { useAction } from "@web/core/action_port";
import { evaluateExpr } from "@web/core/py_js/py";
import { sharedComponents } from "@web/core/shared_components";
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/ui/dialog/confirmation_dialog";

/**
 * @param {HTMLElement | null} el
 * @param {() => Promise<any>} fct
 * @returns {Promise<any>}
 */
export async function executeButtonCallback(el, fct) {
    /** @type {Element[]} */
    let btns = [];
    function disableButtons() {
        btns = [
            ...(el ? el.querySelectorAll("button:not([disabled])") : []),
            ...document.querySelectorAll(".o-overlay-container button:not([disabled])"),
        ];
        for (const btn of btns) {
            btn.setAttribute("disabled", "1");
        }
    }

    function enableButtons() {
        for (const btn of btns) {
            btn.removeAttribute("disabled");
        }
    }

    disableButtons();
    let res;
    try {
        res = await fct();
    } finally {
        enableButtons();
    }
    return res;
}

function undefinedAsTrue(val) {
    return val === undefined || val;
}

/**
 * @typedef {Object} ViewButtonsOptions
 * @property {Function} [afterExecuteAction]
 * @property {Function} [beforeExecuteAction]
 * @property {Function} [reload]
 */

/**
 * @param {Record<string, any>} clickParams
 * @param {Record<string, any>} params the button's record parameters
 * @returns {Record<string, any>}
 */
function buildButtonContext(clickParams, params) {
    let buttonContext = {};
    if (clickParams.context) {
        buttonContext =
            typeof clickParams.context === "string"
                ? evaluateExpr(clickParams.context, params.evalContext)
                : clickParams.context;
    }
    if (clickParams.buttonContext) {
        Object.assign(buttonContext, clickParams.buttonContext);
    }
    return buttonContext;
}

/**
 * Run one view button click end to end: the before hooks, the action, the
 * after hook, then the dialog it may close.
 *
 * @param {Object} deps
 * @param {any} deps.action
 * @param {any} deps.comp
 * @param {any} deps.env
 * @param {ViewButtonsOptions} deps.options
 * @param {Object} click
 * @param {Record<string, any>} click.clickParams
 * @param {() => Record<string, any>} click.getResParams
 * @param {() => any} [click.beforeExecute]
 * @param {boolean} [click.newWindow]
 */
async function executeViewButton(
    { action, comp, env, options },
    { clickParams, getResParams, beforeExecute, newWindow },
) {
    let _continue = true;
    if (beforeExecute) {
        _continue = undefinedAsTrue(await beforeExecute());
    }
    _continue =
        _continue && undefinedAsTrue(await options.beforeExecuteAction?.(clickParams));
    if (!_continue) {
        return;
    }
    const closeDialog =
        (clickParams.close || clickParams.special) && env.dialogData?.close;
    const params = getResParams();
    const doActionParams = {
        ...clickParams,
        resModel: params.resModel,
        resId: params.resId,
        resIds: params.resIds,
        context: params.context || {},
        buttonContext: buildButtonContext(clickParams, params),
        onClose: async (onCloseInfo) => {
            if (
                !closeDialog &&
                status(comp) !== "destroyed" &&
                !onCloseInfo?.noReload
            ) {
                await options.reload?.();
            }
        },
    };
    let error;
    try {
        await action.doActionButton(doActionParams, { newWindow });
    } catch (_e) {
        error = _e;
    }
    await options.afterExecuteAction?.(clickParams);
    if (closeDialog) {
        closeDialog();
    }
    if (error) {
        return Promise.reject(error);
    }
}

/**
 * @param {any} dialog
 * @param {Record<string, any>} clickParams
 * @param {() => Promise<any>} execute
 * @returns {Promise<void>}
 */
function confirmThenExecute(dialog, clickParams, execute) {
    return new Promise((resolve) => {
        const dialogProps = {
            ...(clickParams["confirm-title"] && {
                title: clickParams["confirm-title"],
            }),
            ...(clickParams["confirm-label"] && {
                confirmLabel: clickParams["confirm-label"],
            }),
            ...(clickParams["cancel-label"] && {
                cancelLabel: clickParams["cancel-label"],
            }),
            body: clickParams.confirm,
            confirm: () => execute(),
            cancel: () => {},
        };
        dialog.add(ConfirmationDialog, dialogProps, {
            onClose: /** @type {any} */ (resolve),
        });
    });
}

/**
 * @param {{ readonly el: HTMLElement | null; }} ref
 * @param {ViewButtonsOptions} [options={}]
 */
export function useViewButtons(ref, options = {}) {
    const action = useAction();
    const dialog = useService("dialog");
    const comp = useComponent();
    const env = useEnv();
    const deps = { action, comp, env, options };

    function getEl() {
        if (env.inDialog) {
            const el = ref.el;
            return el ? el.closest(".modal") : null;
        } else {
            return ref.el;
        }
    }

    useSubEnv({
        async onClickViewButton(click) {
            const execute = () => executeViewButton(deps, click);
            const el = /** @type {HTMLElement} */ (getEl());
            if (click.clickParams.confirm) {
                return executeButtonCallback(el, () =>
                    confirmThenExecute(dialog, click.clickParams, execute),
                );
            }
            return executeButtonCallback(el, execute);
        },
    });
}

sharedComponents.add("executeButtonCallback", executeButtonCallback);
sharedComponents.add("useViewButtons", useViewButtons);
