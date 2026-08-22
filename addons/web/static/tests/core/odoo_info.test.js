// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { publishOdooInfo } from "@web/core/odoo_info";
import { session } from "@web/session";

describe.current.tags("headless");

/**
 * @param {Record<string, any>} sessionPatch
 */
function withSession(sessionPatch) {
    const previousInfo = /** @type {any} */ (odoo).info;
    patchWithCleanup(session, sessionPatch);
    patchWithCleanup(odoo, { info: previousInfo });
}

test("publishOdooInfo forwards the session fields verbatim", () => {
    withSession({
        db: "somedb",
        server_version: "19.0+e",
        server_version_info: [19, 0, 0, "final", 0, "e"],
    });

    expect(publishOdooInfo()).toBe(true);
    expect(odoo.info).toEqual({
        db: "somedb",
        server_version: "19.0+e",
        server_version_info: [19, 0, 0, "final", 0, "e"],
        isEnterprise: true,
    });
});

test("publishOdooInfo reports community when the version tail is not 'e'", () => {
    withSession({
        db: "somedb",
        server_version: "19.0",
        server_version_info: [19, 0, 0, "final", 0, ""],
    });

    expect(publishOdooInfo()).toBe(false);
    expect(odoo.info?.isEnterprise).toBe(false);
});

test("publishOdooInfo survives a session with no server_version_info", () => {
    withSession({
        db: "somedb",
        server_version: undefined,
        server_version_info: undefined,
    });

    expect(publishOdooInfo()).toBe(false);
    expect(odoo.info?.isEnterprise).toBe(false);
    expect(odoo.info?.db).toBe("somedb");
});
