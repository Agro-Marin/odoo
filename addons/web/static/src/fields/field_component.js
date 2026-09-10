// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";

import { fieldHandle } from "./field_handle.js";

/**
 * @template [P=any]
 * @extends {Component<P>}
 */
export class FieldComponent extends Component {
    /** @returns {import("./field_handle.js").FieldHandle} */
    get field() {
        return fieldHandle(this);
    }
}
