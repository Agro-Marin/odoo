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

/**
 * REGRESSION SUITE for the unified navigation clock (audit U3 proposal 4).
 *
 * One race per historical incident class, each asserted from the public
 * surface. The single supersession authority is `am.navigation`
 * (`navigation_token.js`); the mount stage keeps its occupancy sensor but
 * speaks the same `SupersededError`. These tests pin the CONTRACT of the
 * unification:
 *
 *  - a navigation superseded at the LOAD stage rejects with SupersededError;
 *  - a navigation superseded later (mount / skeleton) settles quietly;
 *  - in every case the LAST navigation the user asked for is what renders,
 *    and no superseded dispatch leaves the manager hanging.
 */

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
    // Incident class: a slow /web/action/load answering after the user has
    // already navigated elsewhere. The stale navigation must reject at the
    // load stage - eagerly, with the documented error - and must not repaint.
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

    // The rejection must not wait for the slow load to answer.
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
    // Every superseded dispatch settled - rejected with the documented error
    // at the load stage or resolved quietly past it - and the winner resolved.
    expect(outcomes.at(-1)?.status).toBe("fulfilled");
    for (const outcome of outcomes.slice(0, -1)) {
        if (outcome.status === "rejected") {
            expect(outcome.reason).toBeInstanceOf(SupersededError);
        }
    }
});

test("a doAction minted during a loadState's reconstruction supersedes it", async () => {
    // Incident class: the user hits Back (loadState starts rebuilding the
    // breadcrumb stack from the url), then clicks something else before the
    // reconstruction lands. The click is the newer intent: the loadState must
    // die with the documented error instead of dispatching a stale action
    // over the user's choice.
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
    // The mirror race: a doAction is still waiting on its load RPC when the
    // user hits Back. The Back is the newer intent; the doAction must reject
    // NOW - not mount late over the restored state.
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
    // The counter-example that keeps the mount stage on its occupancy sensor
    // rather than the navigation clock: the dialog mints a newer epoch but
    // takes no container, so the skeleton-stage dispatch must keep going and
    // land - not die parked on its skeleton wait, stranding the skeleton on
    // screen behind the dialog. Landing then closes the dialog, as every
    // inline landing does (`dialog.closeAll` precedes the controller UPDATE);
    // what this pins is that the dispatch SURVIVES, with the pre-unification
    // outcome.
    await mountWithCleanup(WebClient);
    const action = getService("action");

    let skeletonPosted = false;
    action.env.bus.addEventListener(AppEvent.ACTION_MANAGER_UPDATE, (ev) => {
        if (ev.detail?.Component?.name === "SkeletonView") {
            skeletonPosted = true;
        }
    });

    const beneath = action.doAction(22, { clearBreadcrumbs: true });
    // Let the inline dispatch get past its load stage and park on the
    // skeleton wait; the dialog must supersede nothing when it opens.
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
