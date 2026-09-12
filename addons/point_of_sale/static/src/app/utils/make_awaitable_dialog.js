/** @odoo-module native */
import { makeLogger } from "@web/core/debug/debug_logger";
import { ConfirmationDialog } from "@web/ui/dialog";
const log = makeLogger("pos.dialog");
export function makeAwaitable(dialog, comp, props, options) {
    const endDialog = log.perf(`makeAwaitable ${comp.name}`);
    log.lifecycle("makeAwaitable: open", () => ({ component: comp.name }));
    return new Promise((resolve) => {
        dialog.add(
            comp,
            {
                ...props,
                getPayload: (response) => {
                    endDialog({
                        component: comp.name,
                        payload: response !== undefined,
                    });
                    resolve(response);
                },
            },
            {
                ...options,
                onClose: () => {
                    endDialog({ component: comp.name, closed: true });
                    resolve();
                },
            },
        );
    });
}

export function makeActionAwaitable(action, config, additionalArgs) {
    const endAction = log.perf(`makeActionAwaitable ${config}`);
    log.lifecycle("makeActionAwaitable: open", () => ({
        action: config,
        resId: additionalArgs?.props?.resId,
    }));
    return new Promise((resolve) => {
        action.doAction(config, {
            ...additionalArgs,
            props: {
                ...additionalArgs?.props,
                onSave: (record) => {
                    endAction({ action: config, saved: record?.resId });
                    action.doAction({
                        type: "ir.actions.act_window_close",
                    });
                    resolve(record);
                },
            },
        });
    });
}

export function ask(dialog, props, options, comp = ConfirmationDialog) {
    log.lifecycle("ask: open", () => ({ component: comp.name, title: props?.title }));
    return new Promise((resolve) => {
        const answer = (value, how) => {
            log.logic("ask: answered", () => ({
                component: comp.name,
                title: props?.title,
                how,
                value,
            }));
            resolve(value);
        };
        dialog.add(
            comp,
            {
                ...props,
                confirm: () => answer(true, "confirm"),
                cancel: () => answer(false, "cancel"),
            },
            {
                ...options,
                onClose: () => answer(false, "close"),
            },
        );
    });
}
