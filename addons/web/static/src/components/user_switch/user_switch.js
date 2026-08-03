// @ts-check
/** @odoo-module native */

/** @module @web/components/user_switch/user_switch */

import { Component, onMounted, useEffect, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { getLastConnectedUsers, setLastConnectedUsers } from "@web/core/user";
import { imageUrl } from "@web/core/utils/urls";

export class UserSwitch extends Component {
    static template = "web.login_user_switch";
    static props = {};

    setup() {
        const users = getLastConnectedUsers();
        this.root = useRef("root");
        this.state = useState({
            users,
            displayUserChoice: users.length > 1,
        });
        /** @type {HTMLFormElement | null} */
        this.form = null;
        onMounted(() => {
            this.form = document.querySelector("form.oe_login_form");
            if (!this.form) {
                return;
            }
            const hideForm = users.length > 1;
            this.form.classList.toggle("d-none", hideForm);
            if (!hideForm) {
                this.form.querySelector(":placeholder-shown")?.focus();
            }
        });
        useEffect(
            (el) => el?.querySelector("button.list-group-item-action")?.focus(),
            () => [this.root.el],
        );
    }

    toggleFormDisplay() {
        this.state.displayUserChoice =
            !this.state.displayUserChoice && this.state.users.length > 0;
        if (!this.form) {
            return;
        }
        this.form.classList.toggle("d-none", this.state.displayUserChoice);
        this.form.querySelector(":placeholder-shown")?.focus();
    }

    /** @param {{ partnerId: number, partnerWriteDate: any }} param0 */
    getAvatarUrl({ partnerId, partnerWriteDate: unique }) {
        return imageUrl("res.partner", partnerId, "avatar_128", { unique });
    }

    /**
     * One label per row rather than one shared wording: a reader moving
     * through the list would otherwise hear the same sentence at every stop,
     * with nothing to say which account it drops.
     *
     * @param {{ name: string }} user
     * @returns {string}
     */
    removeLabel({ name }) {
        return _t("Remove %s from the list", name);
    }

    /** @param {any} deletedUser */
    remove(deletedUser) {
        this.state.users = this.state.users.filter(
            (/** @type {any} */ user) => user !== deletedUser,
        );
        setLastConnectedUsers(this.state.users);
        if (!this.state.users.length) {
            this.fillForm();
        }
    }

    fillForm(login = "") {
        if (this.form) {
            const loginInput = /** @type {HTMLInputElement | null} */ (
                this.form.querySelector("input#login")
            );
            const passwordInput = /** @type {HTMLInputElement | null} */ (
                this.form.querySelector("input#password")
            );
            if (loginInput) {
                loginInput.value = login;
            }
            if (passwordInput) {
                passwordInput.value = "";
            }
        }
        this.toggleFormDisplay();
    }
}

registry
    .category("public_components")
    .add("web.user_switch", /** @type {any} */ (UserSwitch));
