// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { user } from "@web/core/user";
import { canActOnScssErrors } from "@web/ui/scss_error_display";

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
