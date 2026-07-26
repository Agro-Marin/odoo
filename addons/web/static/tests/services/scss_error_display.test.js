// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { canActOnScssErrors } from "@web/services/scss_error_display";
import { user } from "@web/services/user";

describe.current.tags("headless");

// The service itself can only be exercised through a browser tour: it scrapes
// `document.styleSheets`, which has no meaningful mock. Its *policy* is a plain
// predicate, so pin that here — both directions. The "regular user sees
// nothing" half has no tour covering it, and it is the half that silently broke
// `css_error_tour_frontend` (which runs as the public user) when the gate was
// introduced.

test("an administrator is shown style errors", () => {
    patchWithCleanup(user, { isAdmin: true });
    patchWithCleanup(odoo, { debug: "" });
    expect(canActOnScssErrors()).toBe(true);
});

test("debug mode shows style errors to a non-administrator", () => {
    patchWithCleanup(user, { isAdmin: false });
    patchWithCleanup(odoo, { debug: "1" });
    expect(canActOnScssErrors()).toBe(true);
});

test("a regular user in production is not shown style errors", () => {
    patchWithCleanup(user, { isAdmin: false });
    patchWithCleanup(odoo, { debug: "" });
    expect(canActOnScssErrors()).toBe(false);
});

test("the policy returns a boolean, never a debug string", () => {
    // `odoo.debug` is a string ("1", "assets", ""), so a bare `||` would leak
    // it to callers that expect a boolean.
    patchWithCleanup(user, { isAdmin: false });
    patchWithCleanup(odoo, { debug: "assets" });
    expect(canActOnScssErrors()).toBe(true);
});
