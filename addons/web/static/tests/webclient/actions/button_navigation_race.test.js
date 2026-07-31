// @ts-check

import { expect, test } from "@odoo/hoot";
import { click } from "@odoo/hoot-dom";
import { animationFrame, Deferred } from "@odoo/hoot-mock";
import { Component, onWillStart, xml } from "@odoo/owl";
import {
    contains,
    defineActions,
    defineModels,
    fields,
    getService,
    models,
    mountWithCleanup,
    onRpc,
    webModels,
} from "@web/../tests/web_test_helpers";
import { registry } from "@web/core/registry";
import { WebClient } from "@web/webclient/webclient";

const { ResCompany, ResPartner, ResUsers } = webModels;

/**
 * Stands in for whatever the user navigates to while a button is in flight —
 * in the failing `main_flow_tour` step that is the enterprise home menu, which
 * is likewise an `ir.actions.client` taking over the current controller.
 */
class DestinationAction extends Component {
    static template = xml`<div class="test_destination">Destination</div>`;
    static props = ["*"];
}
registry.category("actions").add("test_destination", DestinationAction);

/**
 * Same, but its mount can be held open, so a test can keep the navigation
 * in flight while something else enters the action manager's KeepLast.
 */
/** @type {any} */
export let slowDestinationDef = null;
class SlowDestinationAction extends Component {
    static template = xml`<div class="test_slow_destination">Slow destination</div>`;
    static props = ["*"];
    setup() {
        onWillStart(() => slowDestinationDef);
    }
}
registry.category("actions").add("test_slow_destination", SlowDestinationAction);

class Partner extends models.Model {
    _rec_name = "display_name";
    display_name = fields.Char();
    _records = [{ id: 1, display_name: "First record" }];
    _views = {
        form: `
            <form>
                <header>
                    <button name="object" string="Call method" type="object"/>
                </header>
                <field name="display_name"/>
            </form>`,
        list: `<list><field name="display_name"/></list>`,
        search: `<search/>`,
    };
}

defineModels([Partner, ResCompany, ResPartner, ResUsers]);

defineActions([
    {
        id: 3,
        xml_id: "action_3",
        name: "Partners",
        res_model: "partner",
        views: [
            [false, "list"],
            [false, "form"],
        ],
    },
    {
        id: 9,
        xml_id: "action_9",
        name: "Destination",
        tag: "test_destination",
        type: "ir.actions.client",
    },
    {
        id: 10,
        xml_id: "action_10",
        name: "Slow destination",
        tag: "test_slow_destination",
        type: "ir.actions.client",
    },
]);

test.tags("desktop");
test("a navigation made during a button's RPC supersedes the button", async () => {
    // Entering the action manager's KeepLast is what protects the navigation:
    // the button's `call_button` wrapper is still pending, so `doAction`
    // rejects it with a SupersededError and the close it would have produced
    // is never dispatched.
    const def = new Deferred();
    onRpc("/web/dataset/call_button/*", () => def);

    await mountWithCleanup(WebClient);
    await getService("action").doAction(3, { viewType: "form", props: { resId: 1 } });
    expect(".o_form_view").toHaveCount(1);

    click(".o_form_view button[name='object']");
    await animationFrame();

    def.resolve(false);
    await getService("action").doAction(9);
    expect(".test_destination").toHaveCount(1);
    expect(".o_form_view").toHaveCount(0);

    await animationFrame();
    await animationFrame();

    expect(".test_destination").toHaveCount(1);
    expect(".o_form_view").toHaveCount(0);
});

test.tags("desktop");
test("a button that saves first must not cancel a navigation made while it saved", async () => {
    // A button clicked on a dirty record saves before it runs, so its
    // `call_button` reaches the KeepLast only *after* a navigation the user
    // started later — entry order inverts the two user intents. The button
    // then runs to completion, and its `onClose` reloads the controller it
    // belonged to while that controller sits under the new one.
    const saveDef = new Deferred();
    onRpc("web_save", () => saveDef);
    // Returning nothing is what makes the action manager synthesise
    // `ir.actions.act_window_close`, exactly as `button_mark_done` does here.
    onRpc("/web/dataset/call_button/*", () => false);

    await mountWithCleanup(WebClient);
    await getService("action").doAction(3);
    await contains(".o_list_view .o_data_cell").click();
    expect(".o_form_view").toHaveCount(1);

    // Dirty the record so the button click has to save before it can run.
    await contains(".o_field_widget[name=display_name] input").edit("changed", {
        confirm: false,
    });
    click(".o_form_view button[name='object']");
    await animationFrame();

    // The user gives up waiting and navigates.
    getService("action").doAction(9);
    await animationFrame();

    // The save lands, and only now does the button's own RPC start.
    saveDef.resolve();
    await animationFrame();
    await animationFrame();
    await animationFrame();

    expect(".test_destination").toHaveCount(1);
    expect(".o_form_view").toHaveCount(0);
});

test.tags("desktop");
test("a bare act_window_close must not disturb an unrelated current controller", async () => {
    // What `button_mark_done` ultimately dispatches once its RPC returns
    // nothing. With no dialog open, a close has nothing of its own to shut —
    // and by then the user may be somewhere else entirely.
    await mountWithCleanup(WebClient);
    await getService("action").doAction(3, { viewType: "form", props: { resId: 1 } });
    expect(".o_form_view").toHaveCount(1);

    await getService("action").doAction(9);
    expect(".test_destination").toHaveCount(1);

    await getService("action").doAction({ type: "ir.actions.act_window_close" });
    await animationFrame();

    expect(".test_destination").toHaveCount(1);
    expect(".o_form_view").toHaveCount(0);
});

test.tags("desktop");
test("a button entering the KeepLast must not cancel a navigation already under way", async () => {
    // The tour's ordering. The user clicks the button, then immediately opens
    // the home menu; the button is still saving, so the navigation reaches the
    // action manager first and is mid-mount when the button's `call_button`
    // finally enters the KeepLast behind it. Last-in-wins then cancels the
    // navigation the user made *after* the click.
    slowDestinationDef = new Deferred();
    const saveDef = new Deferred();
    onRpc("web_save", () => saveDef);
    onRpc("/web/dataset/call_button/*", () => false);

    await mountWithCleanup(WebClient);
    await getService("action").doAction(3);
    await contains(".o_list_view .o_data_cell").click();
    await contains(".o_field_widget[name=display_name] input").edit("changed", {
        confirm: false,
    });

    click(".o_form_view button[name='object']");
    await animationFrame();

    // The navigation starts while the button is still saving, and stays
    // pending on its own mount.
    getService("action").doAction(10);
    await animationFrame();

    // The save lands: the button's RPC now enters the KeepLast *behind* the
    // navigation that is already under way.
    saveDef.resolve();
    await animationFrame();
    await animationFrame();

    slowDestinationDef.resolve();
    await animationFrame();
    await animationFrame();

    expect(".test_slow_destination").toHaveCount(1);
    expect(".o_form_view").toHaveCount(0);
});
