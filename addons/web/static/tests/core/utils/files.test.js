// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { allowTranslations, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { localization } from "@web/core/l10n/localization";
import { checkFileSize, DEFAULT_MAX_FILE_SIZE } from "@web/core/utils/files";
import { session } from "@web/session";

describe.current.tags("headless");

function enableFormatting() {
    allowTranslations();
    patchWithCleanup(localization, {
        decimalPoint: ".",
        thousandsSep: ",",
        grouping: [3, 0],
    });
}

/**
 * @returns {{ add: (message: string, options?: any) => () => void, calls: {message: string, options: any}[] }}
 */
function makeNotification() {
    /** @type {{message: string, options: any}[]} */
    const calls = [];
    return {
        calls,
        add(message, options) {
            calls.push({ message, options });
            return () => {};
        },
    };
}

test("checkFileSize: under the limit passes and does not notify", () => {
    const notif = makeNotification();
    expect(checkFileSize(DEFAULT_MAX_FILE_SIZE - 1, notif)).toBe(true);
    expect(notif.calls).toHaveLength(0);
});

test("checkFileSize: exactly at the limit passes (boundary is strict >)", () => {
    const notif = makeNotification();
    expect(checkFileSize(DEFAULT_MAX_FILE_SIZE, notif)).toBe(true);
    expect(notif.calls).toHaveLength(0);
});

test("checkFileSize: over the limit fails and notifies as danger", () => {
    enableFormatting();
    const notif = makeNotification();
    expect(checkFileSize(DEFAULT_MAX_FILE_SIZE + 1, notif)).toBe(false);
    expect(notif.calls).toHaveLength(1);
    expect(notif.calls[0].options).toEqual({ type: "danger" });
    expect(notif.calls[0].message).toMatch(/larger than the maximum allowed/);
});

test("checkFileSize: session.max_file_upload_size overrides the default", () => {
    enableFormatting();
    patchWithCleanup(session, { max_file_upload_size: 1024 });
    const notif = makeNotification();
    expect(checkFileSize(2000, notif)).toBe(false);
    expect(notif.calls).toHaveLength(1);
    expect(checkFileSize(1000, notif)).toBe(true);
    expect(notif.calls).toHaveLength(1);
});

test("checkFileSize: a falsy session cap falls back to the default", () => {
    enableFormatting();
    patchWithCleanup(session, { max_file_upload_size: 0 });
    const notif = makeNotification();
    expect(checkFileSize(DEFAULT_MAX_FILE_SIZE, notif)).toBe(true);
    expect(checkFileSize(DEFAULT_MAX_FILE_SIZE + 1, notif)).toBe(false);
});
