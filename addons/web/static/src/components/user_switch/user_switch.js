// @ts-check
/** @odoo-module native */

import { Component, onMounted, useEffect, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { getLastConnectedUsers, setLastConnectedUsers } from "@web/core/user";
import { imageUrl } from "@web/core/utils/urls";

export class UserSwitch extends Component {
    static template = "web.login_user_switch";
    static props = {};

    /** @type {import("@odoo/owl").Ref<HTMLElement>} */
    root;
    /** @type {{ users: any[], displayUserChoice: boolean }} */
    state;
    /**
     * @type {HTMLFormElement | null}
     */
    form = null;

    setup() {
        const users = getLastConnectedUsers();
        this.root = useRef("root");
        this.state = useState({
            users,
            displayUserChoice: users.length > 1,
        });
        onMounted(() => {
            this.form = document.querySelector("form.oe_login_form");
            if (!this.form) {
                return;
            }
            // The login form is hidden exactly while the user is being offered a
            // choice, which is what `displayUserChoice` already says. Deriving
            // it here from a second, different threshold (`> 1` against
            // `toggleFormDisplay`'s `> 0`) was two spellings of one predicate.
            this.syncFormDisplay();
        });
        useEffect(
            (el) => el?.querySelector("button.list-group-item-action")?.focus(),
            () => [this.root.el],
        );
    }

    syncFormDisplay() {
        if (!this.form) {
            return;
        }
        this.form.classList.toggle("d-none", this.state.displayUserChoice);
        if (!this.state.displayUserChoice) {
            /** @type {HTMLElement | null} */ (
                this.form.querySelector(":placeholder-shown")
            )?.focus();
        }
    }

    toggleFormDisplay() {
        this.state.displayUserChoice =
            !this.state.displayUserChoice && this.state.users.length > 0;
        this.syncFormDisplay();
    }

    /** @param {{ partnerId: number, partnerWriteDate: any }} param0 */
    getAvatarUrl({ partnerId, partnerWriteDate: unique }) {
        return imageUrl("res.partner", partnerId, "avatar_128", { unique });
    }

    /**
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
