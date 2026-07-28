// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { EventBus } from "@odoo/owl";
import { ActionManager } from "@web/webclient/actions/action_service";

/**
 * BRANCH COVERAGE for ``ActionManager.restore``, with NO OWL MOUNT.
 *
 * The virtual-controller branch re-derives an action request from the
 * controller's URL state and re-dispatches it. That makes it the one place
 * where a ``getActionParams`` result — expressed in URL actionStack
 * coordinates — is handed to ``doAction``, which expresses ``options.index``
 * in CONTROLLER stack coordinates. The two are not interchangeable, so the
 * translation is worth pinning independently of a full boot.
 */

/** A manager whose collaborators are stubbed down to what ``restore`` reaches. */
function makeManager({ actionParams, controllerStack }) {
    const env = /** @type {any} */ ({
        bus: new EventBus(),
        services: {},
    });
    const am = new ActionManager(
        env,
        /** @type {any} */ ({
            current: {},
            pushState() {},
            stateToUrl: () => "",
            hideKeyFromUrl() {},
        }),
    );
    am.controllerStack = controllerStack;
    am._getActionParams = () => actionParams;
    am._confirmLeave = async () => true;
    const calls = [];
    am.doAction = async (actionRequest, options) => {
        calls.push({ actionRequest, options });
    };
    /** @type {any} */ (am).__calls = calls;
    return am;
}

/** A virtual (URL-derived) controller, as ``controllersFromState`` builds them. */
function virtualController(jsId) {
    return {
        jsId,
        virtual: true,
        action: {},
        props: {},
        state: { action: 7, actionStack: [{ action: 7 }] },
        currentState: {},
    };
}

describe.current.tags("desktop");

test("restoring a virtual controller re-dispatches its action request", async () => {
    const am = makeManager({
        actionParams: { actionRequest: 7, options: { viewType: "form" } },
        controllerStack: [virtualController("a"), virtualController("b")],
    });

    await am.restore("b");

    const calls = /** @type {any} */ (am).__calls;
    expect(calls).toHaveLength(1);
    expect(calls[0].actionRequest).toBe(7);
    expect(calls[0].options.viewType).toBe("form");
    expect(calls[0].options.isBreadcrumbRestore).toBe(true);
    // Everything below the restored controller stays as breadcrumbs.
    expect(calls[0].options.newStack.map((c) => c.jsId)).toEqual(["a"]);
});

test("poppedLeaves from getActionParams is not forwarded to doAction", async () => {
    // `getActionParams` reports how many URL actionStack entries it had to pop
    // to resolve a request. Here the position is already fixed by the explicit
    // `newStack`, so the count has no meaning left and must not ride along.
    const am = makeManager({
        actionParams: {
            actionRequest: 7,
            options: { poppedLeaves: 2, viewType: "form" },
        },
        controllerStack: [virtualController("a"), virtualController("b")],
    });

    await am.restore("b");

    const { options } = /** @type {any} */ (am).__calls[0];
    expect("poppedLeaves" in options).toBe(false);
    // The rest of the params still comes through untouched.
    expect(options.viewType).toBe("form");
    expect(options.newStack.map((c) => c.jsId)).toEqual(["a"]);
});
