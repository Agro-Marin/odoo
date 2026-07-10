// @ts-check

import { ServerModel } from "../mock_model.js";

export class ResLang extends ServerModel {
    _name = "res.lang";

    _records = [{ id: 1, code: "en_US", name: "English (US)", direction: "ltr" }];

    /**
     * Default ``get_installed`` mock matching the production endpoint shape:
     * a list of ``[code, name]`` tuples for every active language. Tests that
     * need richer data should ``onRpc("res.lang", "get_installed", () => […])``
     * to override this.
     */
    get_installed() {
        return /** @type {any} */ (this._records).map((r) => [r.code, r.name]);
    }
}
