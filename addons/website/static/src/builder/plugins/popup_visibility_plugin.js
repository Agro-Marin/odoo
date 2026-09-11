/** @odoo-module native */
import { getBootstrapComponent } from "@html_builder/core/bootstrap_realm";
import { Plugin } from "@html_editor/plugin";
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";

/**
 * @typedef { Object } PopupVisibilityShared
 * @property { PopupVisibilityPlugin['onTargetHide'] } onTargetHide
 * @property { PopupVisibilityPlugin['onTargetShow'] } onTargetShow
 */

export class PopupVisibilityPlugin extends Plugin {
    static id = "popupVisibilityPlugin";
    static dependencies = ["visibility", "history"];
    static shared = ["onTargetShow", "onTargetHide"];

    /** @type {import("plugins").WebsiteResources} */
    resources = {
        target_show: this.onTargetShow.bind(this),
        target_hide: this.onTargetHide.bind(this),
        clean_for_save_handlers: this.cleanForSave.bind(this),
        on_restore_containers_handlers: this.hidePopupsWithoutTarget.bind(this),
        on_reveal_target_handlers: this.hidePopupsWithoutTarget.bind(this),
    };

    setup() {
        this.addDomListener(this.editable, "click", (ev) => {
            if (ev.target.matches(".s_popup .js_close_popup:not(a, .btn)")) {
                ev.stopPropagation();
                const popupEl = ev.target.closest(".s_popup");
                this.dependencies.visibility.hideElement(popupEl);
            }
        });
        const history = this.dependencies.history;
        const Modal = this.getModal();
        this.unpatchModal = Modal
            ? patch(Modal.prototype, {
                  _hideModal() {
                      return history.ignoreDOMMutations(() => super._hideModal());
                  },
                  show() {
                      return history.ignoreDOMMutations(() => super.show());
                  },
                  hide() {
                      return history.ignoreDOMMutations(() => super.hide());
                  },
              })
            : () => {};
    }

    /**
     * @returns {Function|undefined}
     */
    getModal() {
        return getBootstrapComponent(this.window, "Modal");
    }

    destroy() {
        super.destroy();
        this.unpatchModal();
    }

    /**
     * @param {HTMLElement} targetEl
     * @returns {HTMLElement|null}
     */
    getModalEl(targetEl) {
        return targetEl.matches(".s_popup") ? targetEl.querySelector(".modal") : null;
    }

    onTargetShow(targetEl) {
        if (!this.editable.contains(targetEl)) {
            return;
        }
        const modalEl = this.getModalEl(targetEl);
        const Modal = this.getModal();
        if (modalEl && Modal) {
            Modal.getOrCreateInstance(modalEl).show();
        }
    }

    onTargetHide(targetEl, isCleaning) {
        if (isCleaning) {
            return;
        }
        const modalEl = this.getModalEl(targetEl);
        const Modal = this.getModal();
        if (modalEl && Modal) {
            Modal.getOrCreateInstance(modalEl).hide();
        }
    }

    cleanForSave({ root: rootEl }) {
        const Modal = this.getModal();
        if (!Modal) {
            return;
        }
        for (const modalEl of rootEl.querySelectorAll(".s_popup .modal.show")) {
            modalEl.parentElement.dataset.invisible = "1";
            modalEl.classList.remove("show");
            const modal = Modal.getOrCreateInstance(modalEl);
            modal._hideModal();
            modal.dispose();
        }
    }

    /**
     * @param {HTMLElement} targetEl
     */
    hidePopupsWithoutTarget(targetEl) {
        const openPopupEls = this.editable.querySelectorAll(
            ".s_popup:not([data-invisible='1'])",
        );
        if (!openPopupEls.length) {
            return;
        }

        for (const popupEl of openPopupEls) {
            if (!popupEl.contains(targetEl)) {
                this.dependencies.visibility.toggleTargetVisibility(popupEl, false);
            }
        }
        this.config.updateInvisibleElementsPanel();
    }
}

registry
    .category("website-plugins")
    .add(PopupVisibilityPlugin.id, PopupVisibilityPlugin);
