// @ts-check
/** @odoo-module native */

import { Component, useRef, useState } from "@odoo/owl";
import { CheckBox } from "@web/components/checkbox/checkbox";
import { AccordionItem } from "@web/components/dropdown/accordion_item";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { useDropdownState } from "@web/components/dropdown/dropdown_hook";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { isActivationKey } from "@web/core/browser/hotkeys";
import { EmbeddedActions } from "@web/search/embedded_actions_bar/embedded_actions";

/** @import { EmbeddedAction } from "@web/search/embedded_actions_bar/embedded_actions" */

export class EmbeddedActionsDropdown extends Component {
    static template = "web.EmbeddedActionsDropdown";
    static components = { Dropdown, DropdownItem, AccordionItem, CheckBox };
    static props = {
        embeddedActions: EmbeddedActions,
        state: { type: Object, optional: true },
    };

    /** @type {{el: HTMLElement | null}} */
    newActionNameRef;
    /** @type {import("@web/components/dropdown/dropdown_hook").DropdownState} */
    dropdownState;
    /** @type {{embeddedInfos: EmbeddedActions["embeddedInfos"]}} */
    state;

    setup() {
        this.newActionNameRef = useRef("newActionNameRef");
        const ownDropdownState = useDropdownState();
        this.dropdownState = this.props.state || ownDropdownState;
        this.state = useState({
            embeddedInfos: this.props.embeddedActions.embeddedInfos,
        });
    }

    /**
     * @param {EmbeddedAction} action
     * @returns {string}
     */
    getDropdownClass(action) {
        const isCurrent =
            this.state.embeddedInfos.currentEmbeddedAction?.id === action.id;
        const isVisible = EmbeddedActions.isVisible(this.state.embeddedInfos, action);
        return (this.env.isSmall ? isCurrent : isVisible) ? "selected" : "";
    }

    /**
     * @param {EmbeddedAction} action
     */
    onEmbeddedActionClick(action) {
        return this.props.embeddedActions.openAction(action);
    }

    /**
     * @param {number|false} actionId
     */
    setVisibility(actionId) {
        return this.props.embeddedActions.toggleActionVisibility(actionId);
    }

    /**
     * @param {EmbeddedAction} action
     */
    openConfirmationDialog(action) {
        return this.props.embeddedActions.confirmDelete(action);
    }

    /**
     * @param {KeyboardEvent} ev
     * @param {EmbeddedAction} action
     */
    onDeleteKeydown(ev, action) {
        if (!isActivationKey(ev)) {
            return;
        }
        ev.preventDefault();
        ev.stopPropagation();
        this.openConfirmationDialog(action);
    }

    onShareCheckboxChange() {
        this.state.embeddedInfos.newActionIsShared =
            !this.state.embeddedInfos.newActionIsShared;
    }

    /**
     * @param {Event} ev
     */
    async saveNewAction(ev) {
        const saved = await this.props.embeddedActions.saveNewAction();
        if (!saved) {
            ev.stopPropagation();
            this.newActionNameRef.el?.focus();
        }
    }
}
