// @ts-check

import { animationFrame } from "@odoo/hoot";
import { Component, xml } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { ActionContainer } from "@web/webclient/actions/action_container";
import { WebClient } from "@web/webclient/webclient";

import { mountWithCleanup } from "./component_test_helpers.js";

class TestClientAction extends Component {
    static template = xml`
        <div class="test_client_action">
            ClientAction_<t t-esc="props.action.params?.description"/>
        </div>`;
    static props = ["*"];
}

export function useTestClientAction() {
    const tag = "__test__client__action__";
    registry.category("actions").add(tag, TestClientAction);
    return {
        tag,
        target: "main",
        type: "ir.actions.client",
        params: { description: "Id 1" },
    };
}

/**
 * Mount ONLY the action container — the minimum the action service needs to
 * be observable — instead of the whole ``WebClient``.
 *
 * ``getService("action")`` already returns a real ``ActionManager`` from a bare
 * ``makeMockEnv()``, but ``doAction`` never settles without a renderer: the
 * dispatch promise is resolved by ``ControllerComponent``'s ``onMounted``, so
 * with nothing listening to ``ACTION_MANAGER:UPDATE`` every awaiter hangs
 * forever. That is the only reason action tests reach for a ``WebClient``
 * mount; the navbar, menu service and router plumbing it drags in are
 * incidental for anything that isn't testing them.
 *
 * This mounts the production ``ActionContainer`` (not a stand-in, so the test
 * exercises the real event contract). ``mountWithCleanup`` adds a
 * ``MainComponentsContainer`` unless ``noMainContainer`` is set, so the dialog
 * and overlay services work too — ``target="new"`` actions render normally.
 *
 * Use ``mountWebClient`` when the test needs the shell (breadcrumb DOM, navbar,
 * URL/menu resolution); use this when it only needs the action manager.
 *
 * @param {Parameters<typeof mountWithCleanup>[1]} [options]
 * @returns {Promise<ActionContainer>}
 */
export async function mountActionHost(options = {}) {
    return mountWithCleanup(ActionContainer, options);
}

/**
 * @param {Parameters<typeof mountWithCleanup>[1]} [options]
 */
export async function mountWebClient(options = {}) {
    const WebClientComponent = /** @type {any} */ (options).WebClient || WebClient;
    delete (/** @type {any} */ (options).WebClient);
    const webClient = await mountWithCleanup(WebClientComponent, options);
    await animationFrame();
    await animationFrame();
    await animationFrame();

    return webClient;
}
