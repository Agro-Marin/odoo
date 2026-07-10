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
    // Bare Event, not manuallyDispatchProgrammaticEvent: no need for a full
    // submit event (FormData, method, action, etc.) here.
    const ev = new Event("submit");
    queryOne(".oe_login_form").dispatchEvent(ev);
    expect("button").toHaveClass(["o_btn_loading", "disabled"]);
    ev.preventDefault();
    expect("button").not.toHaveClass(["o_btn_loading", "disabled"]);
});
