// @ts-check

import { ServerModel } from "../mock_model.js";

export class ResLang extends ServerModel {
    _name = "res.lang";

    _records = [{ id: 1, code: "en_US", name: "English (US)", direction: "ltr" }];

    /**
     * Mocks the production shape: ``[code, name]`` tuples for active languages.
     * Override via ``onRpc("res.lang", "get_installed", () => […])`` if needed.
     */
    get_installed() {
        return /** @type {any} */ (this._records).map((r) => [r.code, r.name]);
    }
}
