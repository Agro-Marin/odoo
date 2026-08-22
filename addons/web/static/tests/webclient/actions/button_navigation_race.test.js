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

class DestinationAction extends Component {
    static template = xml`<div class="test_destination">Destination</div>`;
    static props = ["*"];
}
registry.category("actions").add("test_destination", DestinationAction);

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
    const saveDef = new Deferred();
    onRpc("web_save", () => saveDef);
    onRpc("/web/dataset/call_button/*", () => false);

    await mountWithCleanup(WebClient);
    await getService("action").doAction(3);
    await contains(".o_list_view .o_data_cell").click();
    expect(".o_form_view").toHaveCount(1);

    await contains(".o_field_widget[name=display_name] input").edit("changed", {
        confirm: false,
    });
    click(".o_form_view button[name='object']");
    await animationFrame();

    getService("action").doAction(9);
    await animationFrame();

    saveDef.resolve();
    await animationFrame();
    await animationFrame();
    await animationFrame();

    expect(".test_destination").toHaveCount(1);
    expect(".o_form_view").toHaveCount(0);
});

test.tags("desktop");
test("a bare act_window_close must not disturb an unrelated current controller", async () => {
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

    getService("action").doAction(10);
    await animationFrame();

    saveDef.resolve();
    await animationFrame();
    await animationFrame();

    slowDestinationDef.resolve();
    await animationFrame();
    await animationFrame();

    expect(".test_slow_destination").toHaveCount(1);
    expect(".o_form_view").toHaveCount(0);
});
