// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { queryOne } from "@odoo/hoot-dom";
import {
    setupInteractionWhiteList,
    startInteractions,
} from "@web/../tests/public/helpers";

setupInteractionWhiteList("public.login");

describe.current.tags("interaction_dev");

test("add and remove loading effect", async () => {
    const { core } = await startInteractions(`
        <div class="oe_login_form">
            <button type="submit">log in</button>
        </div>`);
    expect(core.interactions).toHaveLength(1);
    const ev = new Event("submit");
    queryOne(".oe_login_form").dispatchEvent(ev);
    expect("button").toHaveClass(["o_btn_loading", "disabled"]);
    ev.preventDefault();
    expect("button").not.toHaveClass(["o_btn_loading", "disabled"]);
});

test("the pressed submit button is the one that spins", async () => {
    await startInteractions(`
        <div class="oe_login_form">
            <button type="submit" class="primary">log in</button>
            <button type="submit" class="secondary" name="redirect">log in as superuser</button>
        </div>`);
    const secondEl = queryOne("button.secondary");
    queryOne(".oe_login_form").dispatchEvent(
        new SubmitEvent("submit", { submitter: secondEl }),
    );
    expect("button.secondary").toHaveClass(["o_btn_loading", "disabled"]);
    expect("button.primary").not.toHaveClass(["o_btn_loading", "disabled"]);
});

test("a submit naming no submitter falls back to the first button", async () => {
    await startInteractions(`
        <div class="oe_login_form">
            <button type="submit" class="primary">log in</button>
            <button type="submit" class="secondary">other</button>
        </div>`);
    queryOne(".oe_login_form").dispatchEvent(new Event("submit"));
    expect("button.primary").toHaveClass(["o_btn_loading", "disabled"]);
    expect("button.secondary").not.toHaveClass(["o_btn_loading", "disabled"]);
});

test("a submit already prevented gets no loading effect at all", async () => {
    await startInteractions(`
        <div class="oe_login_form">
            <button type="submit">log in</button>
        </div>`);
    const ev = new Event("submit", { cancelable: true });
    ev.preventDefault();
    queryOne(".oe_login_form").dispatchEvent(ev);
    expect("button").not.toHaveClass(["o_btn_loading", "disabled"]);
});
