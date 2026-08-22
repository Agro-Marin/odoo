// @ts-check

import { ServerModel } from "../mock_model.js";

export class ResLang extends ServerModel {
    _name = "res.lang";

    _records = [{ id: 1, code: "en_US", name: "English (US)", direction: "ltr" }];

    get_installed() {
        return /** @type {any[]} */ (this._records).map((/** @type {any} */ r) => [
            r.code,
            r.name,
        ]);
    }
}
