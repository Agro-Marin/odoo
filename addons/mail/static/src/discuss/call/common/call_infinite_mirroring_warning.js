/** @odoo-module native */
import { Component } from "@odoo/owl";

/**
 * @typedef {Object} Props
 * @property {Function} onClose
 * @extends {Component<Props, import("@web/env").OdooEnv>}
 */
export class CallInfiniteMirroringWarning extends Component {
    static template = "discuss.CallInfiniteMirroringWarning";
    static props = {
        onClose: { type: Function },
    };
}
