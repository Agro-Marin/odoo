import { expect, test } from "@odoo/hoot";
import {
    IDB_ERROR_LOG_KEY,
    IDB_ERROR_LOG_MAX,
    logPosMessage,
} from "@point_of_sale/app/utils/pretty_console_log";
import { browser } from "@web/core/browser/browser";

const storedErrors = () => JSON.parse(browser.localStorage.getItem(IDB_ERROR_LOG_KEY) || "[]");

test("an error asked to survive a reload is kept outside IndexedDB", async () => {
    // The POS logger writes to IndexedDB. When IndexedDB is what failed, that
    // is the one place the trace cannot be kept.
    browser.localStorage.removeItem(IDB_ERROR_LOG_KEY);
    logPosMessage("IndexedDB", "getNewTransaction.null", "db is null", "#A1A1A1", [], true);

    const kept = storedErrors();
    expect(kept).toHaveLength(1);
    expect(kept[0].type).toBe("IndexedDB");
    expect(kept[0].functionName).toBe("getNewTransaction.null");
    expect(kept[0].message).toBe("db is null");
    expect(kept[0].timestamp).toBeOfType("string");
});

test("an ordinary log is not kept there", async () => {
    browser.localStorage.removeItem(IDB_ERROR_LOG_KEY);
    logPosMessage("Data", "loadData", "loaded 12 models");
    expect(storedErrors()).toHaveLength(0);
});

test("the kept errors do not grow without bound", async () => {
    browser.localStorage.removeItem(IDB_ERROR_LOG_KEY);
    for (let i = 0; i < IDB_ERROR_LOG_MAX + 5; i++) {
        logPosMessage("IndexedDB", "onerror", `failure ${i}`, "#A1A1A1", [], true);
    }
    const kept = storedErrors();
    expect(kept).toHaveLength(IDB_ERROR_LOG_MAX);
    // The oldest go first: what broke last is what a technician needs.
    expect(kept.at(-1).message).toBe(`failure ${IDB_ERROR_LOG_MAX + 4}`);
    expect(kept[0].message).toBe("failure 5");
});
