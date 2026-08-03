// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    makeMockEnv,
    onRpc,
    patchWithCleanup,
    serverState,
} from "@web/../tests/web_test_helpers";
import { browser } from "@web/core/browser/browser";
import { cookie } from "@web/core/browser/cookie";
import { UserEvent } from "@web/core/events";
import { _makeUser, getLastConnectedUsers, user, userBus } from "@web/core/user";

describe.current.tags("headless");

test("successive calls to hasGroup", async () => {
    await makeMockEnv();
    const groups = ["x"];
    onRpc("has_group", (args) => {
        expect.step(`${args.model}/${args.method}/${args.args[1]}`);
        return groups.includes(args.args[1]);
    });

    const hasGroupX = await user.hasGroup("x");
    const hasGroupY = await user.hasGroup("y");
    expect(hasGroupX).toBe(true);
    expect(hasGroupY).toBe(false);
    const hasGroupXAgain = await user.hasGroup("x");
    expect(hasGroupXAgain).toBe(true);

    expect.verifySteps(["res.users/has_group/x", "res.users/has_group/y"]);
});

test("checkAccessRight without context is cached by model/operation/ids", async () => {
    await makeMockEnv();
    onRpc("has_access", (args) => {
        expect.step(`${args.model}/${args.args[1]}/${JSON.stringify(args.args[0])}`);
        return true;
    });

    expect(await user.checkAccessRight("res.partner", "read", 1)).toBe(true);
    expect(await user.checkAccessRight("res.partner", "read", 1)).toBe(true);
    expect(await user.checkAccessRight("res.partner", "write", 1)).toBe(true);

    expect.verifySteps(["res.partner/read/[1]", "res.partner/write/[1]"]);
});

test("checkAccessRight with explicit context bypasses the cache and forwards it", async () => {
    await makeMockEnv();
    onRpc("has_access", (args) => {
        expect.step(
            `${args.args[1]}:${JSON.stringify(args.kwargs.context?.allowed_company_ids)}`,
        );
        return true;
    });

    await user.checkAccessRight("res.partner", "read", 1, {
        context: { allowed_company_ids: [2] },
    });
    await user.checkAccessRight("res.partner", "read", 1, {
        context: { allowed_company_ids: [2] },
    });
    await user.checkAccessRight("res.partner", "read", 1);

    expect.verifySteps(["read:[2]", "read:[2]", "read:[1]"]);
});

test("set user settings do not override old valid keys", async () => {
    await makeMockEnv();
    patchWithCleanup(user, _makeUser({ user_settings: { a: 1, b: 2 } }));
    onRpc("set_res_users_settings", (args) => {
        expect.step(args.kwargs.new_settings);
        return { a: 3, c: 4 };
    });

    expect(user.settings).toEqual({ a: 1, b: 2 });

    await user.setUserSettings("a", 3);
    expect.verifySteps([{ a: 3 }]);
    expect(user.settings).toEqual({ a: 3, b: 2, c: 4 });
});

test("extract allowed company ids from cookies", async () => {
    cookie.set("cids", "3-1");
    serverState.companies = [
        { id: 1, name: "Company 1", sequence: 1, parent_id: false, child_ids: [] },
        { id: 2, name: "Company 2", sequence: 2, parent_id: false, child_ids: [] },
        { id: 3, name: "Company 3", sequence: 3, parent_id: false, child_ids: [] },
    ];

    expect(user.allowedCompanies.map((c) => c.id)).toEqual([1, 2, 3]);
    expect(user.activeCompanies.map((c) => c.id)).toEqual([3, 1]);
    expect(user.activeCompany.id).toBe(3);
});

test("active companies are sorted", async () => {
    serverState.companies = [
        { id: 1, name: "Company 1", sequence: 1, parent_id: false, child_ids: [] },
        { id: 2, name: "Company 2", sequence: 2, parent_id: false, child_ids: [] },
        { id: 3, name: "Company 3", sequence: 3, parent_id: false, child_ids: [] },
    ];

    expect(user.activeCompanies.map((c) => c.id)).toEqual([1]);
    user.activateCompanies([2, 3, 1]);
    expect(user.activeCompanies.map((c) => c.id)).toEqual([2, 1, 3]);
});

test("activate company branches after access error", async () => {
    cookie.set("cids", "1");
    serverState.companies = [
        {
            id: 1,
            name: "Company 1",
            sequence: 1,
            parent_id: false,
            child_ids: [2, 3],
        },
        {
            id: 2,
            name: "Company 1 Branch 1",
            sequence: 2,
            parent_id: 1,
            child_ids: [],
        },
        {
            id: 3,
            name: "Company 1 Branch 2",
            sequence: 3,
            parent_id: 1,
            child_ids: [],
        },
    ];

    const activeCompanyIds = user.activeCompanies.map((c) => c.id);
    activeCompanyIds.push(2);
    user.activateCompanies(activeCompanyIds);
    expect(cookie.get("cids")).toBe("1-2-3");
});

test("activateCompanies does not mutate the caller's array", async () => {
    cookie.set("cids", "1");
    serverState.companies = [
        { id: 1, name: "Company 1", sequence: 1, parent_id: false, child_ids: [2, 3] },
        { id: 2, name: "Branch 1", sequence: 2, parent_id: 1, child_ids: [] },
        { id: 3, name: "Branch 2", sequence: 3, parent_id: 1, child_ids: [] },
    ];

    const callerIds = [1];
    user.activateCompanies(callerIds, { reload: false });
    expect(callerIds).toEqual([1], { message: "caller's array must not be mutated" });
    expect(cookie.get("cids")).toBe("1-2-3");
});

test("activateCompanies tolerates companies without child_ids", async () => {
    // `child_ids` is optional on a UserCompany (the typedef says so, and
    // `disallowed_ancestor_companies` / `{id}`-only test stubs omit it), but
    // `addCompanies` iterated it raw — `for…of undefined` threw a TypeError
    // and the company switch died halfway, leaving the cookie unwritten.
    patchWithCleanup(cookie, { set: () => {}, get: () => "" });
    const testUser = _makeUser({
        uid: 2,
        user_context: {},
        user_companies: {
            current_company: 1,
            allowed_companies: {
                1: { id: 1, name: "Root", child_ids: [2] },
                2: { id: 2, name: "Child, no child_ids" },
            },
        },
    });
    await testUser.activateCompanies([1], { reload: false });
    expect(testUser.activeCompanies.map((c) => c.id)).toEqual([1, 2]);
});

test("re-selecting the same companies does not fire ACTIVE_COMPANIES_CHANGED", async () => {
    // Every listener of this event invalidates something expensive (the group
    // and access-right caches here, the whole display-name cache in
    // name_service). A no-op switch used to pay for all of it.
    patchWithCleanup(cookie, { set: () => {}, get: () => "" });
    const testUser = _makeUser({
        uid: 2,
        user_context: {},
        user_companies: {
            current_company: 1,
            allowed_companies: {
                1: { id: 1, name: "Root", child_ids: [] },
                2: { id: 2, name: "Other", child_ids: [] },
            },
        },
    });
    let fired = 0;
    const onChange = () => fired++;
    userBus.addEventListener(UserEvent.ACTIVE_COMPANIES_CHANGED, onChange);

    await testUser.activateCompanies([1], { reload: false });
    expect(fired).toBe(0);
    expect(testUser.activeCompanies.map((c) => c.id)).toEqual([1]);

    await testUser.activateCompanies([1, 2], { reload: false });
    expect(fired).toBe(1);

    await testUser.activateCompanies([1, 2], { reload: false });
    expect(fired).toBe(1);

    userBus.removeEventListener(UserEvent.ACTIVE_COMPANIES_CHANGED, onChange);
});

test("a corrupt lastConnectedUsers entry degrades to an empty list", async () => {
    // JSON.parse returns a number/string/object here just as happily as an
    // array; callers then .filter()/.slice() it and throw on every boot.
    browser.localStorage.setItem("web.lastConnectedUser", "42");
    expect(getLastConnectedUsers()).toEqual([]);
    expect(browser.localStorage.getItem("web.lastConnectedUser")).toBe(null);

    browser.localStorage.setItem("web.lastConnectedUser", '{"not":"an array"}');
    expect(getLastConnectedUsers()).toEqual([]);

    browser.localStorage.setItem("web.lastConnectedUser", '[{"userId":7}]');
    expect(getLastConnectedUsers()).toEqual([{ userId: 7 }]);
    browser.localStorage.removeItem("web.lastConnectedUser");
});

test("_makeUser does not mutate the session it is given", () => {
    // It used to `delete` 14 keys off its argument, so it was not idempotent
    // and every caller passing a literal had that literal gutted. The stripping
    // of the real singleton now happens once, at module scope.
    const session = {
        uid: 7,
        name: "Test User",
        partner_id: 3,
        user_context: { lang: "en" },
        is_admin: true,
        groups: ["base.group_user"],
    };
    const before = JSON.parse(JSON.stringify(session));

    const first = _makeUser(session);
    expect(session).toEqual(before);

    // Idempotent: a second call sees the same input and answers the same.
    const second = _makeUser(session);
    expect(session).toEqual(before);
    expect(second.userId).toBe(first.userId);
    expect(second.name).toBe(first.name);
});
