/** @odoo-module native */
import { Component } from "@odoo/owl";

/**
 * @typedef {Object} Props
 * @extends {Component<Props, import("@web/env").OdooEnv>}
 */
export class CountryFlag extends Component {
    static props = ["country", "class?"];
    static template = "mail.CountryFlag";
}
