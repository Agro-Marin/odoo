// @ts-check
/** @odoo-module native */

import { Component } from "@odoo/owl";
import { isMacOS } from "@web/core/browser/feature_detection";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";
import { registry } from "@web/core/registry";

const commandSetupRegistry = registry.category("command_setup");

/** @type {Record<string, any>} */
export const COMMAND_ITEM_PROPS = {
    slots: { type: Object, optional: true },
    name: { type: String, optional: true },
    searchValue: { type: String, optional: true },
    executeCommand: { type: Function, optional: true },
};

export class DefaultCommandItem extends Component {
    static template = "web.DefaultCommandItem";
    static props = { ...COMMAND_ITEM_PROPS };
}

export class DefaultFooter extends Component {
    static template = "web.DefaultFooter";
    static props = {
        switchNamespace: { type: Function },
    };
    /** @returns {{ namespace: string, name: any }[]} */
    get elements() {
        return commandSetupRegistry
            .getEntries()
            .map(([namespace, { name }]) => ({ namespace, name }))
            .filter((el) => el.name);
    }

    onClick(/** @type {string} */ namespace) {
        this.props.switchNamespace(namespace);
    }
}

export class HotkeyCommandItem extends Component {
    static template = "web.HotkeyCommandItem";
    static props = {
        ...COMMAND_ITEM_PROPS,
        hotkey: { type: String },
        hotkeyOptions: { type: Object, optional: true },
    };
    setup() {
        useHotkey(this.props.hotkey, this.props.executeCommand);
    }

    /** @returns {string[]} */
    get keysToPress() {
        /** @type {string[]} */
        let result = this.props.hotkey.split("+");
        if (isMacOS()) {
            result = result
                .map((x) => x.replace("control", "command"))
                .map((x) => x.replace("alt", "control"));
        }
        return result.map((key) => key.toUpperCase());
    }
}
