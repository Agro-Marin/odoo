// @ts-check
/** @odoo-module native */

import { whenReady } from "@odoo/owl";
import { publishOdooInfo } from "@web/core/odoo_info";
import { mountComponent } from "@web/env";
import { session } from "@web/session";

import { PublicReadonlySpreadsheet } from "./public_readonly.js";

/** The element `public_readonly_spreadsheet_templates.xml` renders for this app. */
export const MOUNT_ANCHOR_ID = "spreadsheet-mount-anchor";

/**
 * Boot the public read-only spreadsheet page.
 *
 * Split out of `main.js` so it can be tested: `web.assets_unit_tests` carries
 * `public_readonly_app/**\/*.js` minus `main.js`, exactly as it carries
 * `public/**\/*.js` minus `public_boot_instance.js`. The sequence is testable,
 * the self-executing entry point is not — and while this lived in `main.js` it
 * was in no test bundle at all.
 *
 * @returns {Promise<import("@odoo/owl").App>}
 */
export async function startPublicReadonlySpreadsheet() {
    publishOdooInfo();
    odoo.isReady = false;
    await whenReady();

    const target = document.getElementById(MOUNT_ANCHOR_ID);
    if (!target) {
        // Reached `App.validateTarget` as `null` before, which reports a
        // missing target without naming what was looked for.
        throw new Error(
            `public spreadsheet: no #${MOUNT_ANCHOR_ID} element to mount on`,
        );
    }

    const app = await mountComponent(PublicReadonlySpreadsheet, target, {
        props: session.spreadsheet_public_props,
        // Narrower than mountComponent's default (`!session.test_mode`) on
        // purpose: this page has always warned only in debug, and the flag is
        // inert outside dev mode anyway — OWL emits `validateProps` into a
        // compiled template only under `if (this.dev)`.
        warnIfNoStaticProps: Boolean(odoo.debug),
    });

    odoo.isReady = true;
    return app;
}
