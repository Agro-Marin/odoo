// @ts-check
/** @odoo-module native */

/** @module @web/components/colorlist/colorlist - Expandable color swatch picker for selecting from predefined Odoo color indices */

import { Component, useEffect, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
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

    setup() {
        this.colorlistRef = useRef("colorlist");
        this.state = useState({ isExpanded: this.props.isExpanded });
        this.onOutsideClick = this.onOutsideClick.bind(this);
        // Only listen to outside clicks while expanded; the effect cleanup
        // also removes the listener on unmount.
        useEffect(
            (isExpanded) => {
                if (isExpanded) {
                    window.addEventListener(
                        "click",
                        /** @type {EventListener} */ (this.onOutsideClick),
                    );
                    return () =>
                        window.removeEventListener(
                            "click",
                            /** @type {EventListener} */ (this.onOutsideClick),
                        );
                }
            },
            () => [this.state.isExpanded],
        );
        // Move focus to the first color button *after* the expand render.
        // Focusing synchronously in onToggle would target the collapsed
        // toggler, which the render then removes, dropping focus to <body>.
        useEffect(
            (isExpanded) => {
                if (isExpanded) {
                    /** @type {HTMLElement | null} */ (
                        this.colorlistRef.el?.querySelector("button")
                    )?.focus();
                }
            },
            () => [this.state.isExpanded],
        );
    }
    get colors() {
        return /** @type {any} */ (this.constructor).COLORS;
    }
    onColorSelected(id) {
        this.props.onColorSelected(id);
        if (!this.props.forceExpanded) {
            this.state.isExpanded = false;
        }
    }
    onOutsideClick(/** @type {MouseEvent} */ ev) {
        if (
            this.colorlistRef.el.contains(/** @type {Node} */ (ev.target)) ||
            this.props.forceExpanded
        ) {
            return;
        }
        this.state.isExpanded = false;
    }
    onToggle(ev) {
        if (this.props.canToggle) {
            ev.preventDefault();
            ev.stopPropagation();
            this.state.isExpanded = !this.state.isExpanded;
            // Focusing happens in the isExpanded useEffect, once the color
            // buttons have actually been rendered.
        }
    }
}
