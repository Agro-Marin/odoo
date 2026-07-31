/** @odoo-module native */
import { EventBus } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { AuthUI } from "./auth_ui.js";

const bus = new EventBus();

// Hoisted out of `start`: `main_components` is one global registry and `start`
// runs once per env, so a fresh entry each time makes the second env's add
// either warn and lose (no `force`) or clobber an addon's override (with it).
// The bus is module-level, so one shared entry is also the honest shape.
const AUTH_UI_ENTRY = { Component: AuthUI, props: { bus } };

export const authService = {
    start() {
        registry.category("main_components").add("AuthUI", AUTH_UI_ENTRY);
    },
};
registry.category("services").add("auth_ui", authService);
