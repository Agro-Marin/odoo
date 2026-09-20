/** @odoo-module native */
import { ErrorDialog, odooExceptionTitleMap } from "@web/components/errors";
import { makeLogger } from "@web/core/debug/debug_logger";
import { ConnectionLostError, RPCError } from "@web/core/network";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { AlertDialog } from "@web/ui/dialog";
const log = makeLogger("pos.errors");
export function handleRPCError(error, dialog) {
    const { data } = error;
    log.logic("handleRPCError", () => ({
        exceptionName: error.exceptionName,
        known: odooExceptionTitleMap.has(error.exceptionName),
        message: data?.message,
    }));
    if (odooExceptionTitleMap.has(error.exceptionName)) {
        const title = odooExceptionTitleMap.get(error.exceptionName).toString();
        dialog.add(AlertDialog, { title, body: data.message });
    } else {
        if (odoo.debug === "assets") {
            dialog.add(ErrorDialog, {
                traceback: data.message + "\n" + data.debug + "\n",
            });
        } else {
            dialog.add(AlertDialog, {
                title: _t("Odoo Server Error"),
                body: data.message,
            });
        }
    }
}

function rpcErrorHandler(env, error, originalError) {
    if (originalError instanceof RPCError) {
        log.pipeline("[handler] rpcErrorHandler", () => ({
            exceptionName: originalError.exceptionName,
        }));
        handleRPCError(originalError, env.services.dialog);
        return true;
    }
}
registry.category("error_handlers").add("pos-rpcErrorHandler", rpcErrorHandler);

export function showLimitedFunctionalityWarning(pos) {
    log.logic("showLimitedFunctionalityWarning", () => ({
        alreadyShown: pos.data.network.warningTriggered,
    }));
    if (!pos.data.network.warningTriggered) {
        pos.dialog.add(AlertDialog, {
            title: _t("Connection Lost"),
            body: _t(
                "Until the connection is reestablished, Odoo Point of Sale will operate with limited functionality.",
            ),
            confirmLabel: _t("Continue with limited functionality"),
        });
        pos.data.network.warningTriggered = true;
    }
}

export function offlineErrorHandler(env, error, originalError) {
    if (originalError instanceof ConnectionLostError) {
        log.pipeline("[handler] offlineErrorHandler");
        showLimitedFunctionalityWarning(env.services.pos);
        return true;
    }
}
registry.category("error_handlers").add("pos-offlineErrorHandler", offlineErrorHandler);

function defaultErrorHandler(env, error, originalError) {
    log.pipeline("[handler] defaultErrorHandler", () => ({
        isError: error instanceof Error,
        name: originalError?.constructor?.name,
        message: originalError?.message,
    }));
    if (error instanceof Error) {
        env.services.dialog.add(ErrorDialog, {
            traceback: error.traceback,
        });
    } else {
        env.services.dialog.add(AlertDialog, {
            title: _t("Unknown Error"),
            body: _t("Unable to show information about this error."),
            showReloadButton: true,
        });
    }
    return true;
}
registry
    .category("error_handlers")
    .add("pos-defaultErrorHandler", defaultErrorHandler, { sequence: 99 });
