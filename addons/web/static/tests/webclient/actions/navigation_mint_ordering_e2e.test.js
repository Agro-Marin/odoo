// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { animationFrame, Deferred } from "@odoo/hoot-mock";
import {
    defineActions,
    defineModels,
    fields,
    getService,
    models,
    mountWithCleanup,
    onRpc,
    webModels,
} from "@web/../tests/web_test_helpers";
import { WebClient } from "@web/webclient/webclient";

/**
 * `switchView` bumps the navigation epoch, which rejects the `/web/action/load`
 * every in-flight `doAction` is awaiting. It must not pay that price on the
 * paths where it declines to switch at all, or the pending navigation is
 * destroyed with nothing replacing it — the click is simply lost. `restore` is
 * reached from a breadcrumb's `onSelected`, which neither awaits nor catches,
 * so the loss surfaces as an unhandled rejection.
 *
 * These drive the real service through a mounted WebClient; the unit-level
 * companions live in navigation_mint_ordering.test.js.
 */

describe.current.tags("desktop");

const { ResCompany, ResPartner, ResUsers } = webModels;

class Partner extends models.Model {
    _rec_name = "display_name";
    display_name = fields.Char();
    _records = [{ id: 1, display_name: "First" }];
    _views = {
        list: `<list><field name="display_name"/></list>`,
        kanban: `<kanban><templates><t t-name="card"><field name="display_name"/></t></templates></kanban>`,
        form: `<form><field name="display_name"/></form>`,
        search: `<search/>`,
    };
}

defineModels([Partner, ResCompany, ResPartner, ResUsers]);

defineActions([
    {
        id: 21,
        xml_id: "a21",
        name: "List",
        res_model: "partner",
        views: [
            [false, "list"],
            [false, "form"],
        ],
    },
    {
        id: 22,
        xml_id: "a22",
        name: "Kanban",
        res_model: "partner",
        views: [
            [false, "kanban"],
            [false, "form"],
        ],
    },
    {
        id: 23,
        xml_id: "a23",
        name: "Dialog",
        res_model: "partner",
        target: "new",
        views: [[false, "form"]],
    },
]);

/**
 * Holds the next `/web/action/load` open, and reports how the navigation ended.
 */
function holdNextActionLoad() {
    const held = new Deferred();
    let holding = false;
    onRpc("/web/action/load", async () => {
        if (holding) {
            await held;
        }
    });
    return {
        start: () => (holding = true),
        release: () => held.resolve(),
    };
}

test("a switchView refused by an open dialog does not lose the pending navigation", async () => {
    await mountWithCleanup(WebClient);
    const action = getService("action");
    await action.doAction(21);
    await action.doAction(23);
    await animationFrame();
    expect(".modal").toHaveCount(1);

    const load = holdNextActionLoad();
    load.start();
    let outcome = "pending";
    const navigation = action.doAction(22).then(
        () => (outcome = "resolved"),
        (error) => (outcome = `rejected:${error.constructor.name}`),
    );
    await animationFrame();

    await action.switchView("form");
    load.release();
    await navigation;
    await animationFrame();

    expect(outcome).toBe("resolved");
});

test("a switchView refused by a pending dispatch does not lose the pending navigation", async () => {
    await mountWithCleanup(WebClient);
    const action = getService("action");
    await action.doAction(21);
    action._pendingDispatch = /** @type {any} */ ({
        baseStack: action.controllerStack,
    });

    const load = holdNextActionLoad();
    load.start();
    let outcome = "pending";
    const navigation = action.doAction(22).then(
        () => (outcome = "resolved"),
        (error) => (outcome = `rejected:${error.constructor.name}`),
    );
    await animationFrame();

    await action.switchView("form");
    load.release();
    await navigation;
    await animationFrame();

    expect(outcome).toBe("resolved");
});
