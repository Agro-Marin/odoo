// @ts-check
/** @odoo-module native */

/** @module @web/webclient/debug/profiling/profiling_systray_item - Systray indicator icon shown when Python profiling is active */

import { Component } from "@odoo/owl";

class ProfilingSystrayItem extends Component {
    static template = "web.ProfilingSystrayItem";
    static props = {};
}

export const profilingSystrayItem = {
    Component: ProfilingSystrayItem,
};
