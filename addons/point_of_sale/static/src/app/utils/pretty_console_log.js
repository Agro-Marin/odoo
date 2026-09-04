/** @odoo-module native */
/* eslint-disable no-console -- dedicated styled console logger; console is its output */
import { Logger } from "@bus/workers/bus_worker_utils";
import { browser } from "@web/core/browser/browser";
import { luxon } from "@web/core/l10n/luxon";
import { downloadFile } from "@web/core/network";
const posLogger = new Logger(`point_of_sale_config_${odoo.pos_config_id}_logger`);

// `posLogger` keeps its entries in IndexedDB. When IndexedDB is what failed,
// that is the one place the trace cannot be kept, so those callers ask for a
// copy in localStorage as well.
export const IDB_ERROR_LOG_KEY = "pos_idb_errors";
export const IDB_ERROR_LOG_MAX = 200;

export function logPosMessage(
    type,
    functionName,
    message,
    color = "#A1A1A1",
    args = [],
    persistToStorage = false,
) {
    if (odoo.debug === "assets") {
        console.groupCollapsed(
            `[%c${type}%c]: %c${functionName}%c - ${message}`,
            `color:${color};`,
            "",
            `font-weight:bold;`,
            "",
        );
        if (args.length) {
            console.debug(...args);
        }
        console.trace("Call stack:");
        console.groupEnd();
    }
    const timestamp = luxon.DateTime.now().toUTC().toFormat("yyyy-LL-dd HH:mm:ss");
    const log = {
        timestamp,
        type,
        functionName,
        message,
    };
    if (args.length) {
        try {
            log.args = JSON.parse(JSON.stringify(args));
        } catch {
            log.args = args.toString();
        }
    }
    posLogger.log(log);
    if (persistToStorage) {
        persistIdbError(log);
    }
}

function persistIdbError(log) {
    try {
        const logs = JSON.parse(browser.localStorage.getItem(IDB_ERROR_LOG_KEY) || "[]");
        logs.push(log);
        if (logs.length > IDB_ERROR_LOG_MAX) {
            logs.splice(0, logs.length - IDB_ERROR_LOG_MAX);
        }
        browser.localStorage.setItem(IDB_ERROR_LOG_KEY, JSON.stringify(logs));
    } catch {
        // localStorage can be unavailable too: private mode, quota exhausted.
        // Losing the copy must not swallow the error being reported.
    }
}

export function downloadIdbErrors() {
    const raw = browser.localStorage.getItem(IDB_ERROR_LOG_KEY) || "[]";
    const blob = new Blob([raw], { type: "application/json" });
    const stamp = luxon.DateTime.now().toUTC().toFormat("yyyy-LL-dd-HH-mm-ss");
    downloadFile(blob, `pos_idb_errors_${stamp}.json`);
}

export async function downloadPosLogs() {
    const logs = await posLogger.getLogs();
    const blob = new Blob([JSON.stringify(logs, null, 2)], {
        type: "application/json",
    });
    const filename = `pos_logs_${luxon.DateTime.now()
        .toUTC()
        .toFormat("yyyy-LL-dd-HH-mm-ss")}.json`;
    downloadFile(blob, filename);
}
