// @ts-check
/** @odoo-module native */

/** @module @web/components/dropdown/dropdown - Core dropdown component with popover positioning, nesting, and keyboard navigation */

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
import { useDropdownState } from "@web/components/dropdown/dropdown_hooks";
import { hasTouch } from "@web/core/browser/feature_detection";
import { deepMerge } from "@web/core/utils/collections/objects";
import { mergeClasses } from "@web/core/utils/dom/classname";
import { useChildRef, useService } from "@web/core/utils/hooks";
import { disposableEffect } from "@web/core/utils/reactive";
import { useNavigation } from "@web/services/navigation/navigation";
import { utils } from "@web/ui/block/ui_service";
import { usePopover } from "@web/ui/popover/popover_hook";

/**
 * @param {any} node
 * @returns {HTMLElement | null}
 */
export function getFirstElementOfNode(node) {
    if (!node) {
        return null;
    }
    if (node.el) {
        return node.el.nodeType === Node.ELEMENT_NODE ? node.el : null;
    }
    if (node.bdom || node.child) {
        return getFirstElementOfNode(node.bdom || node.child);
    }
    if (node.children) {
        for (const child of node.children) {
            const el = getFirstElementOfNode(child);
            if (el) {
                return el;
            }
        }
    }
    return null;
}

/**
 * A menu that shows itself when a target is toggled. Items are DropdownItems;
 * dropdowns can be nested as items to build nested menus.
 */
export class Dropdown extends Component {
    static template = xml`<t t-slot="default"/>`;
    static components = {};
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
            // OWL validates array-element shapes under the singular `element` key
            // (see validateType in owl.js); the plural `elements` is inert.
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

        menuRef: { type: Function, optional: true }, // to be used with useChildRef
        disabled: { type: Boolean, optional: true },
        holdOnHover: { type: Boolean, optional: true },
        focusToggleOnClosed: { type: Boolean, optional: true },

        beforeOpen: { type: Function, optional: true },
        onOpened: { type: Function, optional: true },
        onStateChanged: { type: Function, optional: true },

        /** Manual state handling, @see useDropdownState */
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

        /** When true, do not add optional styling css classes on the target*/
        noClasses: { type: Boolean, optional: true },

        /** Override the internal navigation hook options */
        navigationOptions: { type: Object, optional: true },
        bottomSheet: { type: Boolean, optional: true },
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
        this._boundHandleClick = this.handleClick.bind(this);
        this._boundHandleMouseEnter = this.handleMouseEnter.bind(this);

        this.state = this.props.state || useDropdownState();
        this.nesting = useDropdownNesting(this.state);
        this.group = useDropdownGroup();

        this.navigation = useNavigation(this.menuRef, {
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
            // Using deepMerge allows to keep entries of both option.hotkeys
            ...deepMerge(this.nesting.navigationOptions, this.props.navigationOptions),
        });

        // Exposed for navigable children (DropdownItem, AccordionItem, etc.), which
        // read ``this.env.navigation``; propagates through the portal since the
        // popover is mounted with the dropdown's ``childEnv``.
        useChildSubEnv({ navigation: this.navigation });

        this.uiService = useService("ui");

        const getPosition = () => this.position;
        /** @type {any} */
        const options = {
            animation: false,
            arrow: false,
            closeOnClickAway: (target) => this.popoverCloseOnClickAway(target),
            closeOnEscape: false, // Handled via navigation and prevents closing root of nested dropdown
            env: /** @type {any} */ (this).__owl__.childEnv,
            holdOnHover: this.props.holdOnHover,
            onClose: () => this.state.close(),
            onPositioned: (el, { direction }) =>
                this.setTargetDirectionClass(direction),
            popoverClass: mergeClasses(
                "o-dropdown--menu dropdown-menu mx-0",
                { "o-dropdown--menu-submenu": this.hasParent },
                this.props.menuClass,
            ),
            role: "menu",
            get position() {
                return getPosition();
            },
            ref: this.menuRef,
            setActiveElement: false,
        };
        if (this.isBottomSheet) {
            Object.assign(options, {
                useBottomSheet: true,
                class: mergeClasses(
                    "o-dropdown--menu dropdown-menu show",
                    this.props.menuClass,
                ),
            });
        }
        this.popover = usePopover(DropdownPopover, options);

        // Force the popover to re-render since it lives in a separate context.
        onRendered(() =>
            this.popoverRefresher ? this.popoverRefresher.token++ : null,
        );

        onMounted(() => this.onStateChanged(this.state));
        const disposeEffect = disposableEffect(
            (state) => this.onStateChanged(state),
            [this.state],
        );
        onWillDestroy(disposeEffect);

        useEffect(
            (target) => this.setTargetElement(target),
            () => [this.target],
        );

        onWillUpdateProps(({ disabled }) => {
            if (disabled) {
                this.state.close();
                this.closePopover();
            }
        });
    }

    get isBottomSheet() {
        return utils.isSmall() && hasTouch() && this.props.bottomSheet;
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
        // Returns null when the toggler element is absent (teardown, or a
        // conditionally-rendered/empty slot). Every consumer already guards for
        // null (`this.target?.`, `if (!this.target)`, `if (this.target)`); the
        // previous `throw` made those guards dead code and crashed the close
        // path (onClosed/updatePopoverPosition) instead of no-op'ing.
        return getFirstElementOfNode(/** @type {any} */ (this).__owl__.bdom);
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
            // Don't steal focus from an editable element the user is typing in
            // (outside this dropdown) on a pure mouse-over.
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

    /**
     * Snapshot the element to restore focus to on close, taken at the opening
     * gesture — BEFORE state.open() kicks off the dropdown-nesting reactive
     * cascade. Opening this dropdown closes any open sibling, and that sibling
     * restores its own focus first; reading document.activeElement later (in
     * openPopover) would capture the sibling's restored element and land focus
     * there on close instead of on our toggler.
     */
    _captureFocusBeforeOpen() {
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

        target.classList.add(...requiredClasses);
        if (!this.props.noClasses) {
            target.classList.add(...optionalClasses);
        }

        this.defaultDirection = this.position.split("-")[0];
        this.setTargetDirectionClass(this.defaultDirection);

        if (!this.props.manual) {
            target.addEventListener("click", this._boundHandleClick);
            target.addEventListener("mouseenter", this._boundHandleMouseEnter);

            return () => {
                target.removeEventListener("click", this._boundHandleClick);
                target.removeEventListener("mouseenter", this._boundHandleMouseEnter);
            };
        }
    }

    setTargetDirectionClass(direction) {
        if (!this.target || this.props.noClasses) {
            return;
        }
        const directionClasses = {
            bottom: "dropdown",
            top: "dropup",
            left: "dropstart",
            right: "dropend",
        };
        this.target.classList.remove(...Object.values(directionClasses));
        this.target.classList.add(directionClasses[direction]);
    }

    openPopover() {
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
        // Restore-focus anchor: prefer the element captured at the opening gesture
        // (before the nesting cascade), falling back to activeElement for
        // programmatic opens. Keep the captured element so closing gives focus
        // back to where the user was (e.g. a composer input for a message
        // action dropdown) — UNLESS it belongs to another dropdown (a sibling
        // closing concurrently may have claimed focus on its own toggler/menu),
        // in which case anchor on this dropdown's own toggler.
        const captured =
            this._pendingFocusEl !== undefined
                ? this._pendingFocusEl
                : /** @type {HTMLElement | null} */ (document.activeElement);
        this._pendingFocusEl = undefined;
        const capturedInOtherDropdown =
            captured &&
            !this.target.contains(captured) &&
            Boolean(
                captured.closest?.(".o-dropdown, .o-dropdown--menu, .dropdown-menu"),
            );
        // Also never restore into a rich-text editable: re-focusing it resets
        // its DOM selection, corrupting the edition flow the dropdown acted on
        // (e.g. the html_editor toolbar's format dropdowns).
        const capturedUsable =
            captured && !capturedInOtherDropdown && !captured.isContentEditable;
        this._focusedElBeforeOpen = capturedUsable ? captured : this.target;
        this.popover.open(this.target, props);
    }

    closePopover() {
        this.popover.close();
        if (this.props.focusToggleOnClosed && !this.group.isInGroup) {
            this._focusedElBeforeOpen?.focus();
            this._focusedElBeforeOpen = undefined;
        }
    }

    onOpened() {
        this.activeEl = this.uiService.activeElement;
        this.navigation.registerHotkeys();
        this.navigation.update();
        this.props.onOpened?.();
        this.props.onStateChanged?.(true);

        if (this.target) {
            this.target.ariaExpanded = "true";
            this.target.classList.add("show");
        }

        this.observer = new MutationObserver(() => this.navigation.update());
        this.observer.observe(this.menuRef.el, {
            childList: true,
            subtree: true,
        });
    }

    onClosed() {
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
