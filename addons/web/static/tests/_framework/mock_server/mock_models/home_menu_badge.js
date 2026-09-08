// @ts-check

import { ServerModel } from "../mock_model.js";

export class HomeMenuBadge extends ServerModel {
    _name = "home.menu.badge";

    /**
     * No counts unless a suite says otherwise. The launcher asks for these on
     * every mount, so a mock server that does not answer makes every suite in
     * the tree log a failed provider — which is what it did before this model
     * existed.
     *
     * @returns {Record<string, number>}
     */
    get_badges() {
        return {};
    }
}
