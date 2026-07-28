// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { canActOnScssErrors } from "@web/services/scss_error_display";
import { user } from "@web/services/user";

describe.current.tags("headless");

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
    patchWithCleanup(user, { isAdmin: false });
    patchWithCleanup(odoo, { debug: "assets" });
    expect(canActOnScssErrors()).toBe(true);
});
