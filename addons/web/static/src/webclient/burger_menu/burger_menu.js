// @ts-check
/** @odoo-module native */

import { Component, useState } from "@odoo/owl";
import { AppEvent } from "@web/core/events";
import { registry } from "@web/core/registry";
import { Transition } from "@web/core/transition";
import { user } from "@web/core/user";
import { useBus } from "@web/core/utils/hooks";

import { SWIPE_RIGHT, SwipeTracker } from "../swipe.js";
import { BurgerUserMenu } from "./burger_user_menu/burger_user_menu.js";
import { MobileSwitchCompanyMenu } from "./mobile_switch_company_menu/mobile_switch_company_menu.js";

export class BurgerMenu extends Component {
    static template = "web.BurgerMenu";
    static props = {};
    static components = {
        BurgerUserMenu,
        MobileSwitchCompanyMenu,
        Transition,
    };

    /** @type {{ isBurgerOpened: boolean }} */
    state;
    /** @type {SwipeTracker} */
    swipe;

    setup() {
        this.user = user;
        this.state = useState({
            isBurgerOpened: false,
        });
        this.swipe = new SwipeTracker(SWIPE_RIGHT);
        useBus(this.env.bus, AppEvent.HOME_MENU_TOGGLED, () => {
            this._closeBurger();
        });
        useBus(
            this.env.bus,
            AppEvent.ACTION_MANAGER_UPDATE,
            /** @type {any} */ (
                (/** @type {{ detail: any }} */ ev) => {
                    if (ev.detail.id) {
                        this._closeBurger();
                    }
                }
            ),
        );
    }
    _closeBurger() {
        this.state.isBurgerOpened = false;
    }
    _openBurger() {
        this.state.isBurgerOpened = true;
    }
    /** @param {any} ev */
    _onSwipeStart(ev) {
        this.swipe.start(ev);
    }
    /** @param {any} ev */
    _onSwipeEnd(ev) {
        if (this.swipe.end(ev)) {
            this._closeBurger();
        }
    }
}

const systrayItem = {
    Component: BurgerMenu,
};

registry.category("systray").add("burger_menu", systrayItem, { sequence: 0 });
