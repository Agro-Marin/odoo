// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { animationFrame, Deferred, microTick } from "@odoo/hoot-mock";
import {
    defineActions,
    defineModels,
    fields,
    getService,
    models,
    mountWithCleanup,
    patchWithCleanup,
    webModels,
} from "@web/../tests/web_test_helpers";
import { AppEvent } from "@web/core/events";
import { SupersededError } from "@web/core/utils/concurrency";
import { WebClient } from "@web/webclient/webclient";

describe.current.tags("desktop");

const { ResCompany, ResPartner, ResUsers } = webModels;

class Partner extends models.Model {
    _rec_name = "display_name";
    display_name = fields.Char();
    _records = [
        { id: 1, display_name: "First record" },
        { id: 2, display_name: "Second record" },
    ];
    _views = {
        list: `<list><field name="display_name"/></list>`,
        kanban: `
            <kanban>
                <templates>
                    <t t-name="card">
                        <field name="display_name"/>
                    </t>
                </templates>
            </kanban>`,
        form: `<form><field name="display_name"/></form>`,
        search: `<search/>`,
    };
}

defineModels([Partner, ResCompany, ResPartner, ResUsers]);

defineActions([
    {
        id: 21,
        xml_id: "action_21",
        name: "Partners list",
        res_model: "partner",
        views: [[false, "list"]],
    },
    {
        id: 22,
        xml_id: "action_22",
        name: "Partners kanban",
        res_model: "partner",
        views: [[false, "kanban"]],
    },
]);

test("a stale doAction whose load resolves late cannot dispatch", async () => {
    const slowLoad = new Deferred();
    await mountWithCleanup(WebClient);
    const action = getService("action");

    patchWithCleanup(action, {
        async _loadAction(request, context) {
            if (request === 21) {
                await slowLoad;
            }
            return super._loadAction(request, context);
        },
    });

    const stale = action.doAction(21).then(
        () => "resolved",
        (error) => error,
    );
    await animationFrame();

    await action.doAction(22);
    expect(".o_kanban_view").toHaveCount(1);

    expect(await stale).toBeInstanceOf(SupersededError);

    slowLoad.resolve();
    await animationFrame();
    await animationFrame();
    expect(".o_kanban_view").toHaveCount(1, {
        message: "the late resolution is dropped, the newer view stays",
    });
    expect(".o_list_view").toHaveCount(0);
});

test("rapid navigation: the last of a burst wins, none of it hangs", async () => {
    await mountWithCleanup(WebClient);
    const action = getService("action");

    const outcomes = await Promise.allSettled([
        action.doAction(21),
        action.doAction(22),
        action.doAction(21),
        action.doAction(22),
    ]);
    await animationFrame();

    expect(".o_kanban_view").toHaveCount(1);
    expect(".o_list_view").toHaveCount(0);
    expect(outcomes.at(-1)?.status).toBe("fulfilled");
    for (const outcome of outcomes.slice(0, -1)) {
        if (outcome.status === "rejected") {
            expect(outcome.reason).toBeInstanceOf(SupersededError);
        }
    }
});

test("a doAction minted during a loadState's reconstruction supersedes it", async () => {
    const reconstruction = new Deferred();
    await mountWithCleanup(WebClient);
    const action = getService("action");

    patchWithCleanup(action, {
        async _controllersFromState(state) {
            await reconstruction;
            return super._controllersFromState(state);
        },
    });

    const stale = action.loadState({ action: 21 }).then(
        () => "resolved",
        (error) => error,
    );
    await animationFrame();

    await action.doAction(22);
    expect(".o_kanban_view").toHaveCount(1);

    reconstruction.resolve();
    expect(await stale).toBeInstanceOf(SupersededError);
    await animationFrame();
    expect(".o_kanban_view").toHaveCount(1, {
        message: "the user's click outlives the older Back navigation",
    });
    expect(".o_list_view").toHaveCount(0);
});

test("entering loadState cancels an in-flight doAction load eagerly", async () => {
    const slowLoad = new Deferred();
    await mountWithCleanup(WebClient);
    const action = getService("action");

    patchWithCleanup(action, {
        async _loadAction(request, context) {
            if (request === 21) {
                await slowLoad;
            }
            return super._loadAction(request, context);
        },
    });

    const stale = action.doAction(21).then(
        () => "resolved",
        (error) => error,
    );
    await animationFrame();

    await action.loadState({ action: 22 });
    expect(".o_kanban_view").toHaveCount(1);
    expect(await stale).toBeInstanceOf(SupersededError);

    slowLoad.resolve();
    await animationFrame();
    await animationFrame();
    expect(".o_kanban_view").toHaveCount(1);
    expect(".o_list_view").toHaveCount(0);
});

test("a dialog above a clearBreadcrumbs skeleton does not cancel the dispatch beneath", async () => {
    await mountWithCleanup(WebClient);
    const action = getService("action");

    let skeletonPosted = false;
    action.env.bus.addEventListener(AppEvent.ACTION_MANAGER_UPDATE, (ev) => {
        if (/** @type {any} */ (ev).detail?.Component?.name === "SkeletonView") {
            skeletonPosted = true;
        }
    });

    const beneath = action.doAction(22, { clearBreadcrumbs: true });
    for (let i = 0; i < 50 && !skeletonPosted; i++) {
        await microTick();
    }
    expect(skeletonPosted).toBe(true);
    await action.doAction({
        type: "ir.actions.act_window",
        res_model: "partner",
        target: "new",
        views: [[false, "form"]],
    });
    await beneath;
    await animationFrame();

    expect(".o_kanban_view").toHaveCount(1, {
        message: "the inline dispatch landed; the dialog did not cancel it",
    });
    expect(".o_skeleton_view").toHaveCount(0);
    expect(".o_technical_modal").toHaveCount(0, {
        message: "an inline landing closes the dialogs above it, as always",
    });
});
