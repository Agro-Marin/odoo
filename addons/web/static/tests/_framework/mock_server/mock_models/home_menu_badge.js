// @ts-check

import { ServerModel } from "../mock_model.js";

export class HomeMenuBadge extends ServerModel {
    _name = "home.menu.badge";

    /** @returns {Record<string, number>} */
    get_badges() {
        return {};
    }
}
