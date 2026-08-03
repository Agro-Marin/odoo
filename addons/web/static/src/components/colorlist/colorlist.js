// @ts-check
/** @odoo-module native */

/** @module @web/components/colorlist/colorlist */

import { Component, onWillUpdateProps, useEffect, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/translation";
import { useClickAway } from "@web/core/utils/dom/click_away";
export class ColorList extends Component {
    static COLORS = [
        _t("No color"),
        _t("Red"),
        _t("Orange"),
        _t("Yellow"),
        _t("Cyan"),
        _t("Purple"),
        _t("Almond"),
        _t("Teal"),
        _t("Blue"),
        _t("Raspberry"),
        _t("Green"),
        _t("Violet"),
    ];
    static template = "web.ColorList";
    static defaultProps = {
        forceExpanded: false,
        isExpanded: false,
    };
    static props = {
        canToggle: { type: Boolean, optional: true },
        colors: Array,
        forceExpanded: { type: Boolean, optional: true },
        isExpanded: { type: Boolean, optional: true },
        onColorSelected: Function,
        selectedColor: { type: Number, optional: true },
    };

    /** @type {import("@odoo/owl").Ref} */
    colorlistRef;
    /** @type {{ isExpanded: any }} */
    state;

    setup() {
        this.colorlistRef = useRef("colorlist");
        this.state = useState({ isExpanded: this.props.isExpanded });
        // The toggle also moves this, so it cannot simply mirror the prop: only
        // a caller that actually changes its mind gets to overrule the user.
        onWillUpdateProps((nextProps) => {
            if (nextProps.isExpanded !== this.props.isExpanded) {
                this.state.isExpanded = nextProps.isExpanded;
            }
        });
        useClickAway((node) => this.onOutsideClick(node), {
            getAnchor: () => this.colorlistRef.el,
            getContentEl: () => this.colorlistRef.el,
        });
        // Focus follows the *act* of expanding, not the state of being
        // expanded. A list that arrives open -- `isExpanded`/`forceExpanded`
        // set by the caller -- was not opened by the user, so taking focus
        // there yanks the caret out of whatever they were actually in.
        let hasRun = false;
        useEffect(
            (isExpanded) => {
                const expandedByUser = isExpanded && hasRun;
                hasRun = true;
                if (expandedByUser) {
                    /** @type {HTMLElement | null} */ (
                        this.colorlistRef.el?.querySelector("button")
                    )?.focus();
                }
            },
            () => [this.state.isExpanded],
        );
    }
    /** @returns {string[]} the translated name of each colour index */
    get colorNames() {
        return /** @type {any} */ (this.constructor).COLORS;
    }
    /** @param {number} id */
    onColorSelected(id) {
        this.props.onColorSelected(id);
        if (!this.props.forceExpanded) {
            this.state.isExpanded = false;
        }
    }
    /** @param {Node} [node] */
    onOutsideClick(node) {
        if (
            !this.state.isExpanded ||
            this.props.forceExpanded ||
            this.colorlistRef.el?.contains(node ?? null)
        ) {
            return;
        }
        this.state.isExpanded = false;
    }
    /** @param {MouseEvent} ev */
    onToggle(ev) {
        if (this.props.canToggle) {
            ev.preventDefault();
            ev.stopPropagation();
            this.state.isExpanded = !this.state.isExpanded;
        }
    }
}
