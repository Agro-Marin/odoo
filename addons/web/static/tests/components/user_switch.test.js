// @ts-check

import { beforeEach, expect, getFixture, test } from "@odoo/hoot";
import { queryAll, queryAllTexts, queryFirst, queryOne } from "@odoo/hoot-dom";
import { animationFrame } from "@odoo/hoot-mock";
import { contains, mountWithCleanup } from "@web/../tests/web_test_helpers";
import { UserSwitch } from "@web/components/user_switch/user_switch";
import { browser } from "@web/core/browser/browser";

beforeEach(() => {
    const fixture = getFixture();
    if (!fixture) {
        throw new Error("no hoot fixture: the whole suite depends on it");
    }
    const form = document.createElement("form");
    form.className = "oe_login_form";
    form.innerHTML = `
        <label class="form-label" for="login">Email</label>
        <input id="login" name="login" placeholder="Email"/>
        <input id="password" name="password" type="password"/>
    `;
    fixture.appendChild(form);
});

/**
 * @param {number} count
 */
function rememberUsers(count) {
    const users = Array.from({ length: count }, (_, i) => ({
        login: `user${i}`,
        name: `User ${i}`,
        partnerId: i + 1,
        partnerWriteDate: "2026-01-01 00:00:00",
        userId: i + 1,
    }));
    browser.localStorage.setItem("web.lastConnectedUser", JSON.stringify(users));
    return users;
}

test("several remembered users are offered as a choice", async () => {
    rememberUsers(3);
    await mountWithCleanup(UserSwitch);
    expect(".o_user_switch").toHaveCount(1);
    expect(".o_user_switch_login").toHaveCount(3);
    expect(queryAllTexts(".o_user_switch_login")).toEqual([
        "User 0",
        "User 1",
        "User 2",
    ]);
    expect(".oe_login_form:not(.o_user_switch)").toHaveClass("d-none");
});

test("picking a user fills the form and puts it back on screen", async () => {
    rememberUsers(2);
    await mountWithCleanup(UserSwitch);
    await contains(".o_user_switch_login:first-child").click();
    await animationFrame();
    expect("input#login").toHaveValue("user0");
    expect("input#password").toHaveValue("");
    expect(".oe_login_form:not(.o_user_switch)").not.toHaveClass("d-none");
    expect(".oe_login_form .o_user_switch_btn").toHaveCount(1);
});

test("the chooser rows are containers; the controls inside them do the work", async () => {
    rememberUsers(2);
    await mountWithCleanup(UserSwitch);

    const row = queryOne(".list-group-item:first-child");
    expect(row.tagName).toBe("DIV");
    expect(queryAll("button", { root: row })).toHaveLength(2);

    row.click();
    await animationFrame();
    expect(".oe_login_form:not(.o_user_switch)").toHaveClass("d-none");
    expect("input#login").toHaveValue("");

    await contains(".o_user_switch_login:first-child").click();
    await animationFrame();
    expect("input#login").toHaveValue("user0");
});

test("dropping an account is a control, not decoration", async () => {
    rememberUsers(3);
    await mountWithCleanup(UserSwitch);

    const row = queryFirst(".list-group-item") ?? undefined;
    expect(queryAll("button", { root: row })).toHaveLength(2);
    const remove = queryAll(".o_user_switch_remove")[0];
    expect(remove.tagName).toBe("BUTTON");

    expect(remove).toHaveAttribute("aria-label", "Remove User 0 from the list");
    expect(queryAll(".o_user_switch_remove")[1]).toHaveAttribute(
        "aria-label",
        "Remove User 1 from the list",
    );
    expect(queryOne("i", { root: remove })).toHaveAttribute("aria-hidden", "true");
});

test("dropping an account removes it and remembers that", async () => {
    rememberUsers(3);
    await mountWithCleanup(UserSwitch);
    await contains(".o_user_switch_remove:first").click();
    await animationFrame();

    expect(queryAllTexts(".o_user_switch_login")).toEqual(["User 1", "User 2"]);
    const stored = JSON.parse(
        browser.localStorage.getItem("web.lastConnectedUser") ?? "null",
    );
    expect(stored.map((/** @type {{ login: string }} */ u) => u.login)).toEqual([
        "user1",
        "user2",
    ]);
});

test("dropping the last account hands the form back", async () => {
    rememberUsers(1);
    await mountWithCleanup(UserSwitch);
    expect(".o_user_switch").toHaveCount(0);
    expect(".o_user_switch_btn").toHaveCount(1);
    expect(".oe_login_form").not.toHaveClass("d-none");

    await contains(".o_user_switch_btn").click();
    await animationFrame();
    expect(".o_user_switch_login").toHaveCount(1);

    await contains(".o_user_switch_remove:first").click();
    await animationFrame();
    expect(".o_user_switch").toHaveCount(0);
    expect(".oe_login_form").not.toHaveClass("d-none");
    expect(
        JSON.parse(browser.localStorage.getItem("web.lastConnectedUser") ?? "null"),
    ).toEqual([]);
});

test("the way into the chooser does not jump the page's tab order", async () => {
    rememberUsers(1);
    await mountWithCleanup(UserSwitch);
    expect(".o_user_switch_btn").not.toHaveAttribute("tabindex");
});
