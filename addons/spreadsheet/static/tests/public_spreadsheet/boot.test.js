// @ts-check

import { after, describe, expect, test } from "@odoo/hoot";
import {
    MOUNT_ANCHOR_ID,
    startPublicReadonlySpreadsheet,
} from "@spreadsheet/public_readonly_app/boot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { session } from "@web/session";

describe.current.tags("headless");

/**
 * `odoo.isReady` and `odoo.info` are page globals and the anchor is a real DOM
 * node, so every test puts all three back.
 */
function restoreGlobals() {
    const info = /** @type {any} */ (odoo).info;
    const ready = /** @type {any} */ (odoo).isReady;
    // `after`, not `afterEach`: HOOT refuses a per-suite hook registered from
    // inside a test, and this helper is called by each test that needs it.
    after(() => {
        /** @type {any} */ (odoo).info = info;
        /** @type {any} */ (odoo).isReady = ready;
        document.getElementById(MOUNT_ANCHOR_ID)?.remove();
    });
}

describe("startPublicReadonlySpreadsheet", () => {
    test("names the anchor it could not find", async () => {
        restoreGlobals();
        patchWithCleanup(session, { spreadsheet_public_props: {} });
        expect(document.getElementById(MOUNT_ANCHOR_ID)).toBe(null);

        // Before this boot was extracted, a missing anchor reached
        // `App.validateTarget` as `null`, which reports a bad target without
        // saying what was looked for — on a page whose entire job is to mount
        // one component into one element.
        await expect(startPublicReadonlySpreadsheet()).rejects.toThrow(
            new RegExp(`no #${MOUNT_ANCHOR_ID} element to mount on`),
        );
    });

    test("publishes odoo.info before it can fail on a missing anchor", async () => {
        restoreGlobals();
        patchWithCleanup(session, {
            db: "publicdb",
            server_version: "19.0+e",
            server_version_info: [19, 0, 0, "final", 0, "e"],
            spreadsheet_public_props: {},
        });
        /** @type {any} */ (odoo).info = undefined;

        await startPublicReadonlySpreadsheet().catch(() => {});

        // The page identifies its server even when the mount cannot proceed;
        // `odoo.info` is what the error beacon and the upgrade widgets read.
        // Read through a cast: assigning `undefined` above narrows the declared
        // optional to `never`, so a direct `odoo.info?.db` does not typecheck.
        const info = /** @type {any} */ (odoo).info;
        expect(info?.db).toBe("publicdb");
        expect(info?.isEnterprise).toBe(true);
    });

    test("clears odoo.isReady on entry and does not set it on failure", async () => {
        restoreGlobals();
        patchWithCleanup(session, { spreadsheet_public_props: {} });
        /** @type {any} */ (odoo).isReady = true;

        await startPublicReadonlySpreadsheet().catch(() => {});

        // Tours and `test_click_everywhere.py` poll this. A boot that failed
        // must not leave the previous page's `true` behind.
        expect(odoo.isReady).toBe(false);
    });
});
