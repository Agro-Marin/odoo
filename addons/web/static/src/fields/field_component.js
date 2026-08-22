// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";

import { fieldHandle } from "./field_handle.js";

export class FieldComponent extends Component {
    /** @returns {import("./field_handle.js").FieldHandle} */
    get field() {
        return fieldHandle(this);
    }
}
