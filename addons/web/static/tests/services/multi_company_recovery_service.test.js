// @ts-check

import { expect, test } from "@odoo/hoot";
import {
    getService,
    makeMockEnv,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";
import { user } from "@web/services/user";

/**
 * Build an AccessError shaped like the backend tags a cross-company access
 * failure, with a ``suggested_company`` in the error context.
 * @param {number} companyId
 */
function accessError(companyId) {
    return {
        data: {
            name: "odoo.exceptions.AccessError",
            context: { suggested_company: { id: companyId } },
        },
    };
}

test("recoverFromLifecycleError no-ops when the suggested company is already active", async () => {
    await makeMockEnv();
    patchWithCleanup(user, {
        get activeCompanies() {
            return [{ id: 1 }, { id: 2 }];
        },
        activateCompanies() {
            expect.step("activateCompanies");
        },
    });
    const service = getService("multi_company_recovery");

    // Suggested company (2) is already active: activating + reloading again
    // would loop forever, so the recovery must bail out without side effects.
    const recovered = service.recoverFromLifecycleError(accessError(2), {
        env: {
            pushStateBeforeReload: () => expect.step("pushStateBeforeReload"),
        },
    });

    expect(recovered).toBe(false);
    expect.verifySteps([]);
});

test("recoverFromLifecycleError activates and reloads for a genuinely new company", async () => {
    await makeMockEnv();
    patchWithCleanup(user, {
        get activeCompanies() {
            return [{ id: 1 }];
        },
        activateCompanies(/** @type {number[]} */ ids) {
            expect.step(`activate:${ids.join(",")}`);
        },
    });
    const service = getService("multi_company_recovery");

    const recovered = service.recoverFromLifecycleError(accessError(2), {
        env: {
            pushStateBeforeReload: () => expect.step("pushStateBeforeReload"),
        },
    });

    expect(recovered).toBe(true);
    expect.verifySteps(["pushStateBeforeReload", "activate:1,2"]);
});

test("recoverFromSaveError tolerates a missing allowed_company_ids context", async () => {
    await makeMockEnv();
    patchWithCleanup(user, {
        get activeCompanies() {
            return [{ id: 1 }];
        },
        activateCompanies(/** @type {number[]} */ ids) {
            expect.step(`activate:${ids.join(",")}`);
        },
    });
    const service = getService("multi_company_recovery");
    const model = { config: { context: {} } };

    const recovered = service.recoverFromSaveError(accessError(2), model);

    expect(recovered).toBe(true);
    // The seed must include the user's currently-active companies, not just
    // the suggested one: caller context keys win over user.context in
    // ORM.call, so `[2]` alone would deactivate company 1 server-side for
    // every subsequent RPC of this form session.
    expect(model.config.context.allowed_company_ids).toEqual([1, 2]);
    expect.verifySteps(["activate:1,2"]);
});

test("recoverFromSaveError extends an existing allowed_company_ids context", async () => {
    await makeMockEnv();
    patchWithCleanup(user, {
        get activeCompanies() {
            return [{ id: 1 }];
        },
        activateCompanies(/** @type {number[]} */ ids) {
            expect.step(`activate:${ids.join(",")}`);
        },
    });
    const service = getService("multi_company_recovery");
    const model = { config: { context: { allowed_company_ids: [1, 3] } } };

    const recovered = service.recoverFromSaveError(accessError(2), model);

    expect(recovered).toBe(true);
    expect(model.config.context.allowed_company_ids).toEqual([1, 3, 2]);
    expect.verifySteps(["activate:1,2"]);
});
