// @ts-check
/** @odoo-module native */

import { Component, useEffect, useRef, useState } from "@odoo/owl";
import { useDropdownState } from "@web/components/dropdown/dropdown_hook";
import { browser } from "@web/core/browser/browser";
import { Transition } from "@web/core/transition";
import { useSortable } from "@web/core/utils/dnd/sortable_owl";
import { EmbeddedActions } from "@web/search/embedded_actions_bar/embedded_actions";
import { EmbeddedActionsDropdown } from "@web/search/embedded_actions_bar/embedded_actions_dropdown";

/** @import { EmbeddedAction } from "@web/search/embedded_actions_bar/embedded_actions" */

export class EmbeddedActionsBar extends Component {
    static template = "web.EmbeddedActionsBar";
    static components = {
        EmbeddedActionsDropdown,
        Transition,
    };
    static props = {
        embeddedActions: EmbeddedActions,
    };

    /** @type {{el: HTMLElement | null}} */
    root;
    /** @type {import("@web/components/dropdown/dropdown_hook").DropdownState} */
    dropdownState;
    /** @type {{embeddedInfos: EmbeddedActions["embeddedInfos"]}} */
    state;

    setup() {
        this.root = useRef("root");
        this.dropdownState = useDropdownState();
        this.state = useState({
            embeddedInfos: this.props.embeddedActions.embeddedInfos,
        });

        useEffect(
            (showEmbedded) => {
                const timer = browser.setTimeout(() => {
                    if (
                        showEmbedded &&
                        this.state.embeddedInfos.visibleEmbeddedActions.length === 1
                    ) {
                        this.dropdownState.open();
                    }
                }, 100);
                return () => browser.clearTimeout(timer);
            },
            () => [this.state.embeddedInfos.showEmbedded],
        );

        useSortable(
            /** @type {any} */ ({
                enable: true,
                ref: this.root,
                elements: ".o_draggable",
                cursor: "move",
                delay: 200,
                tolerance: 10,
                onWillStartDrag: (/** @type {any} */ { element, addClass }) =>
                    addClass(element, "o_dragged_embedded_action"),
                onDrop: (/** @type {any} */ params) =>
                    this.props.embeddedActions.reorderFromDrop(params),
            }),
        );
    }

    /**
     * @param {EmbeddedAction} action
     * @returns {boolean}
     */
    _isEmbeddedActionVisible(action) {
        return EmbeddedActions.isVisible(this.state.embeddedInfos, action);
    }
}
