// @ts-check
/** @odoo-module native */
import { discussComponentRegistry } from "@mail/core/common/discuss_component_registry";
import { provideMailContext, useMailContext } from "@mail/utils/common/mail_context";
import { Component, useRef, useState } from "@odoo/owl";
import { useNavigation } from "@web/core/navigation/navigation";
import { usePosition } from "@web/core/position/position_hook";
import { getComponentElement } from "@web/core/utils/components";
import { useMountedListener } from "@web/core/utils/hooks";
import { useLayoutEffect } from "@web/core/utils/layout_effect";
import { useListener } from "@web/core/utils/owl_bridge";
export class CallDropdown extends Component {
    static template = "discuss.CallDropdown";
    static props = {
        position: { type: String, optional: true },
        class: { type: String, optional: true },
        menuClass: { type: String, optional: true },
        slots: { optional: true },
        openByDefault: { type: Boolean, optional: true },
        state: { type: Object, optional: true },
    };
    static defaultProps = {
        position: "bottom",
        class: "",
        menuClass: "",
        openByDefault: false,
    };

    setup() {
        super.setup();
        this.mailContext = useMailContext();
        this.menuRef = useRef("menu");
        this.state = useState({ isOpen: this.props.openByDefault });
        usePosition("menu", () => this.triggerRef.el, {
            position: this.props.position,
            margin: 4,
            flip: true,
        });
        useMountedListener(this.window, "click", this.onClickAway.bind(this), {
            capture: true,
        });
        useListener(this.window, "keydown", this.onKeydown.bind(this));
        provideMailContext({ inCallDropdown: { close: () => this.close() } });
        this.navigation = useNavigation(this.menuRef, {
            isNavigationAvailable: () => this.state.isOpen,
            getItems: () => {
                if (this.state.isOpen && this.menuRef.el) {
                    return Array.from(
                        this.menuRef.el.querySelectorAll(
                            ":scope .o-navigable, :scope .o-dropdown",
                        ),
                    );
                }
                return [];
            },
        });
        this.handleClick = this.handleClick.bind(this);
        useLayoutEffect(
            /** @param {HTMLElement|null} triggerEl */
            (triggerEl) => {
                if (triggerEl) {
                    triggerEl.addEventListener("click", this.handleClick);
                    return () =>
                        triggerEl.removeEventListener("click", this.handleClick);
                }
            },
            () => [this.triggerRef.el],
        );
    }

    get triggerRef() {
        return { el: getComponentElement(this) };
    }

    get window() {
        return this.mailContext.pipWindow || window;
    }

    get isOpen() {
        return this.state.isOpen;
    }

    toggle() {
        this.isOpen ? this.close() : this.open();
    }

    open() {
        this.state.isOpen = true;
    }

    close() {
        this.state.isOpen = false;
    }

    /** @param {MouseEvent} ev */
    handleClick(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        this.toggle();
    }

    /** @param {MouseEvent} ev */
    onClickAway(ev) {
        if (!this.isOpen) {
            return;
        }
        const isOutsideClick =
            !this.triggerRef.el?.contains(/** @type {Node} */ (ev.target)) &&
            !this.menuRef.el?.contains(/** @type {Node} */ (ev.target));
        if (isOutsideClick) {
            this.close();
        }
    }

    /** @param {MouseEvent} ev */
    onClickMenu(ev) {
        ev.stopPropagation();
    }

    /** @param {KeyboardEvent} ev */
    onKeydown(ev) {
        if (ev.key === "Escape" && this.isOpen) {
            ev.preventDefault();
            this.close();
        }
    }
}

discussComponentRegistry.add("CallDropdown", CallDropdown);
