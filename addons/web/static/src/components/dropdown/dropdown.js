// @ts-check
/** @odoo-module native */

import {
    Component,
    onMounted,
    onRendered,
    onWillDestroy,
    onWillUpdateProps,
    reactive,
    status,
    useChildSubEnv,
    useEffect,
    xml,
} from "@odoo/owl";
import { useDropdownGroup } from "@web/components/dropdown/_behaviours/dropdown_group_hook";
import { useDropdownNesting } from "@web/components/dropdown/_behaviours/dropdown_nesting";
import { DropdownPopover } from "@web/components/dropdown/_behaviours/dropdown_popover";
import { useDropdownState } from "@web/components/dropdown/dropdown_hook";
import { hasTouch } from "@web/core/browser/feature_detection";
import { mergeNavigationOptions, useNavigation } from "@web/core/navigation/navigation";
import { getComponentElement } from "@web/core/utils/components";
import { mergeClasses } from "@web/core/utils/dom/classname";
import { uniqueId } from "@web/core/utils/functions";
import { useChildRef, useService } from "@web/core/utils/hooks";
import { disposableEffect } from "@web/core/utils/reactive";
import { usePopover } from "@web/ui/popover/popover_hook";
import { utils } from "@web/ui/viewport";

const DIRECTION_CLASSES = {
    bottom: "dropdown",
    top: "dropup",
    left: "dropstart",
    right: "dropend",
};

const MENU_BOTTOM_SHEET_CLASSES = "o-dropdown--menu dropdown-menu show";
const MENU_INLINE_CLASSES = "o-dropdown--menu dropdown-menu mx-0";
const MENU_SUBMENU_CLASS = "o-dropdown--menu-submenu";

const STATIC_MENU_CLASSES = new Set([
    ...MENU_BOTTOM_SHEET_CLASSES.split(" "),
    ...MENU_INLINE_CLASSES.split(" "),
    MENU_SUBMENU_CLASS,
]);

export class Dropdown extends Component {
    static template = xml`<t t-slot="default"/>`;

    /** @type {string[]} */
    _menuClassNames;

    static props = {
        menuClass: { optional: true },
        position: { type: String, optional: true },
        slots: {
            type: Object,
            shape: {
                default: { optional: true },
                content: { optional: true },
            },
        },

        items: {
            optional: true,
            type: Array,
            element: {
                type: Object,
                shape: {
                    label: String,
                    onSelected: Function,
                    class: { optional: true },
                    "*": true,
                },
            },
        },

        menuRef: { type: Function, optional: true },
        disabled: { type: Boolean, optional: true },
        holdOnHover: { type: Boolean, optional: true },
        focusToggleOnClosed: { type: Boolean, optional: true },

        beforeOpen: { type: Function, optional: true },
        onOpened: { type: Function, optional: true },
        onStateChanged: { type: Function, optional: true },

        state: {
            type: Object,
            shape: {
                isOpen: Boolean,
                close: Function,
                open: Function,
                "*": true,
            },
            optional: true,
        },
        manual: { type: Boolean, optional: true },

        noClasses: { type: Boolean, optional: true },

        navigationOptions: { type: Object, optional: true },
        bottomSheet: { type: Boolean, optional: true },

        role: { type: String, optional: true },

        menuId: { type: String, optional: true },
    };
    static defaultProps = {
        disabled: false,
        holdOnHover: false,
        focusToggleOnClosed: true,
        menuClass: "",
        state: undefined,
        noClasses: false,
        navigationOptions: {},
        bottomSheet: true,
        role: "menu",
    };

    /** @type {any} */
    nesting;
    /** @type {any} */
    group;
    /** @type {any} */
    popover;
    /** @type {any} */
    navigation;
    /** @type {import("services").ServiceFactories["ui"]} */
    uiService;

    setup() {
        this.menuRef = this.props.menuRef || useChildRef();
        this.menuId = this.props.menuId || uniqueId("o-dropdown-menu-");
        this._boundHandleClick = this.handleClick.bind(this);
        this._boundHandleMouseEnter = this.handleMouseEnter.bind(this);

        this.state = this.props.state || useDropdownState();
        this.nesting = useDropdownNesting(this.state);
        this.group = useDropdownGroup();

        this.navigation = useNavigation(
            this.menuRef,
            mergeNavigationOptions(
                {
                    shouldRegisterHotkeys: false,
                    isNavigationAvailable: () => this.state.isOpen,
                    getItems: () => {
                        if (this.state.isOpen && this.menuRef.el) {
                            return this.menuRef.el.querySelectorAll(
                                ":scope .o-navigable, :scope .o-dropdown",
                            );
                        } else {
                            return [];
                        }
                    },
                },
                this.nesting.navigationOptions,
                this.props.navigationOptions,
            ),
        );

        useChildSubEnv({ navigation: this.navigation });

        this.uiService = useService("ui");
        this.setupPopover();
        this.setupTargetBinding();
    }

    setupPopover() {
        const self = this;
        /** @type {any} */
        const options = {
            animation: false,
            arrow: false,
            closeOnClickAway: (target) => this.popoverCloseOnClickAway(target),
            closeOnEscape: false,
            env: /** @type {any} */ (this).__owl__.childEnv,
            holdOnHover: this.props.holdOnHover,
            onClose: () => this.state.close(),
            onPositioned: (el, { direction }) =>
                this.setTargetDirectionClass(direction),
            get role() {
                return self.props.role;
            },
            id: this.menuId,
            get position() {
                return self.position;
            },
            ref: this.menuRef,
            setActiveElement: false,
            useBottomSheet: () => this.isBottomSheet,
            get class() {
                return self.isBottomSheet
                    ? mergeClasses(MENU_BOTTOM_SHEET_CLASSES, self.props.menuClass)
                    : mergeClasses(
                          MENU_INLINE_CLASSES,
                          { [MENU_SUBMENU_CLASS]: self.hasParent },
                          self.props.menuClass,
                      );
            },
        };
        this.popover = usePopover(DropdownPopover, options);

        onRendered(() => {
            if (this.popoverRefresher) {
                this.popoverRefresher.token++;
            }
        });

        onMounted(() => this.onStateChanged(this.state));
        const disposeEffect = disposableEffect(
            (state) => this.onStateChanged(state),
            [this.state],
        );
        onWillDestroy(disposeEffect);
    }

    setupTargetBinding() {
        useEffect(
            (target) => this.setTargetElement(target),
            () => [this.target],
        );

        this._menuClassNames = [];
        useEffect(
            (menuEl) => {
                if (menuEl) {
                    this.syncMenuClass(menuEl);
                }
            },
            () => [this.menuRef.el, this.menuClassNames.join(" ")],
        );

        onWillUpdateProps((nextProps) => {
            if (nextProps.state && nextProps.state !== this.props.state) {
                throw new Error(
                    "Dropdown: the `state` prop is read once, in setup. Hold one " +
                        "object for the life of the component instead of computing " +
                        "a new one per render.",
                );
            }
            if (nextProps.disabled) {
                this.state.close();
                this.closePopover();
            }
        });
    }

    get isBottomSheet() {
        return utils.isSmall() && hasTouch() && this.props.bottomSheet;
    }

    /**
     * @returns {string[]}
     */
    get menuClassNames() {
        const merged = mergeClasses(this.props.menuClass);
        return Object.keys(merged)
            .filter((name) => merged[name] && name.trim())
            .map((name) => name.trim());
    }

    /**
     * @param {HTMLElement} menuEl
     */
    syncMenuClass(menuEl) {
        const wanted = this.menuClassNames;
        for (const name of this._menuClassNames) {
            if (!wanted.includes(name) && !STATIC_MENU_CLASSES.has(name)) {
                menuEl.classList.remove(name);
            }
        }
        menuEl.classList.add(...wanted);
        this._menuClassNames = wanted;
    }

    /** @type {string} */
    get position() {
        return this.props.position || (this.hasParent ? "right-start" : "bottom-start");
    }

    get hasParent() {
        return this.nesting.hasParent;
    }

    /** @type {HTMLElement|null} */
    get target() {
        return getComponentElement(this);
    }

    handleClick(event) {
        if (this.props.disabled) {
            return;
        }

        event.stopPropagation();
        if (this.state.isOpen && !this.hasParent) {
            this.state.close();
        } else {
            this._captureFocusBeforeOpen();
            this.state.open();
        }
    }

    handleMouseEnter() {
        if (this.props.disabled) {
            return;
        }

        if (this.hasParent || this.group.isOpen) {
            const activeElement = /** @type {HTMLElement | null} */ (
                document.activeElement
            );
            const isEditableActive =
                activeElement &&
                (["INPUT", "TEXTAREA"].includes(activeElement.nodeName) ||
                    activeElement.isContentEditable);
            if (!isEditableActive || this.target?.contains(activeElement)) {
                this.target?.focus();
            }
            this._captureFocusBeforeOpen();
            this.state.open();
        }
    }

    _captureFocusBeforeOpen() {
        if (this.state.isOpen) {
            return;
        }
        this._pendingFocusEl = /** @type {HTMLElement | null} */ (
            document.activeElement
        );
    }

    onStateChanged(state) {
        if (state.isOpen) {
            this.openPopover();
        } else {
            this.closePopover();
        }
    }

    popoverCloseOnClickAway(target) {
        const rootNode = target.getRootNode();
        if (rootNode instanceof ShadowRoot) {
            target = rootNode.host;
        }
        return this.uiService.getActiveElementOf(target) === this.activeEl;
    }

    setTargetElement(target) {
        if (!target) {
            return;
        }

        target.ariaExpanded = "false";
        const optionalClasses = [];
        const requiredClasses = [];
        optionalClasses.push("o-dropdown");

        if (this.hasParent) {
            requiredClasses.push("o-dropdown--has-parent");
        }

        const tagName = target.tagName.toLowerCase();
        if (
            ![
                "input",
                "textarea",
                "table",
                "thead",
                "tbody",
                "tr",
                "th",
                "td",
            ].includes(tagName)
        ) {
            optionalClasses.push("dropdown-toggle");
            if (this.hasParent) {
                optionalClasses.push("o-dropdown-item", "dropdown-item");
                requiredClasses.push("o-navigable");

                if (!target.classList.contains("o-dropdown--no-caret")) {
                    requiredClasses.push("o-dropdown-caret");
                }
            }
        }

        const applied = this.props.noClasses
            ? requiredClasses
            : [...requiredClasses, ...optionalClasses];
        const added = applied.filter((cls) => !target.classList.contains(cls));
        target.classList.add(...added);

        this.defaultDirection = this.position.split("-")[0];
        this.setTargetDirectionClass(this.defaultDirection);

        if (!this.props.manual) {
            target.addEventListener("click", this._boundHandleClick);
            target.addEventListener("mouseenter", this._boundHandleMouseEnter);
        }

        return () => {
            target.removeEventListener("click", this._boundHandleClick);
            target.removeEventListener("mouseenter", this._boundHandleMouseEnter);
            target.classList.remove(...added, ...Object.values(DIRECTION_CLASSES));
            target.removeAttribute("aria-expanded");
        };
    }

    setTargetDirectionClass(direction) {
        if (!this.target || this.props.noClasses) {
            return;
        }
        this.target.classList.remove(...Object.values(DIRECTION_CLASSES));
        this.target.classList.add(DIRECTION_CLASSES[direction]);
    }

    openPopover() {
        const captured =
            this._pendingFocusEl !== undefined
                ? this._pendingFocusEl
                : /** @type {HTMLElement | null} */ (document.activeElement);
        this._pendingFocusEl = undefined;

        if (this.popover.isOpen || status(this) !== "mounted") {
            return;
        }
        if (!this.target || !this.target.isConnected) {
            this.state.close();
            return;
        }

        this.popoverRefresher = reactive({ token: 0 });
        const props = {
            beforeOpen: () => this.props.beforeOpen?.(),
            onOpened: () => this.onOpened(),
            onClosed: () => this.onClosed(),
            refresher: this.popoverRefresher,
            items: this.props.items,
            slots: this.props.slots,
        };
        const capturedInOtherDropdown =
            captured &&
            !this.target.contains(captured) &&
            Boolean(
                captured.closest?.(".o-dropdown, .o-dropdown--menu, .dropdown-menu"),
            );
        const capturedUsable =
            captured && !capturedInOtherDropdown && !captured.isContentEditable;
        this._focusedElBeforeOpen = capturedUsable ? captured : this.target;
        this.popover.open(this.target, props);
    }

    closePopover() {
        const restoreEl = this._focusedElBeforeOpen;
        this._focusedElBeforeOpen = undefined;
        const active = document.activeElement;
        this.popover.close();
        if (!this.props.focusToggleOnClosed || !restoreEl) {
            return;
        }
        const focusOutside =
            active &&
            !this.target?.contains(active) &&
            !this.menuRef.el?.contains(active);
        const leaveFocus = this.group.isInGroup
            ? focusOutside && active !== document.body
            : focusOutside &&
              (["INPUT", "TEXTAREA"].includes(active.nodeName) ||
                  /** @type {HTMLElement} */ (active).isContentEditable);
        if (!leaveFocus) {
            restoreEl.focus();
        }
    }

    onOpened() {
        this.syncMenuClass(this.menuRef.el);
        this.activeEl = this.uiService.activeElement;
        this.navigation.registerHotkeys();
        this.navigation.update();
        this.props.onOpened?.();
        this.props.onStateChanged?.(true);

        if (this.target) {
            this.target.ariaExpanded = "true";
            this.target.classList.add("show");
        }
        const menuEl = this.menuRef.el;
        if (menuEl) {
            this.observer = new MutationObserver(() => this.navigation.update());
            this.observer.observe(menuEl, {
                childList: true,
                subtree: true,
            });
        }
    }

    onClosed() {
        this._menuClassNames = [];
        this.navigation.unregisterHotkeys();
        this.navigation.update();
        this.props.onStateChanged?.(false);
        delete this.activeEl;

        if (this.target) {
            this.target.ariaExpanded = "false";
            this.target.classList.remove("show");
            this.setTargetDirectionClass(this.defaultDirection);
        }

        if (this.observer) {
            this.observer.disconnect();
            this.observer = null;
        }
    }
}
