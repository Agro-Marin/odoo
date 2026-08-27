// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";

import { fieldHandle } from "./field_handle.js";

/**
 * The base every field widget extends.
 *
 * Generic in its props, and it has to be: three field components already write
 * `@extends {FieldComponent<TheirProps>}`, and against a non-generic base that
 * annotation does not narrow anything -- it breaks the inheritance chain
 * outright, so `this.props` and even `this.field` stop resolving on the
 * subclass. `gauge_field.js` alone carried sixteen errors from it, all of them
 * that one line.
 *
 * @template [P=any]
 * @extends {Component<P>}
 */
export class FieldComponent extends Component {
    /** @returns {import("./field_handle.js").FieldHandle} */
    get field() {
        return fieldHandle(this);
    }
}
