/** @odoo-module native */
import { Plugin } from "@html_editor/plugin";
import { isEmptyTextNode, isZWS } from "@html_editor/utils/dom_info";
import { closestElement } from "@html_editor/utils/dom_traversal";
import { withSequence } from "@html_editor/utils/resource";
import { reactive } from "@odoo/owl";
import { hasTouch } from "@web/core/browser/feature_detection";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { omit, pick } from "@web/core/utils/collections/objects";
import { memoize } from "@web/core/utils/functions";
import { debounce } from "@web/core/utils/timing";

import { ToolbarMobile } from "./mobile_toolbar.js";
import { composeToolbarButton, Toolbar } from "./toolbar.js";

/** @typedef { import("@html_editor/core/selection_plugin").EditorSelection } EditorSelection */
/** @typedef {import("@html_editor/core/selection_plugin").SelectionData} SelectionData */
/** @typedef { import("@html_editor/core/user_command_plugin").UserCommand } UserCommand */
/** @typedef { import("@web/core/translation.js")._t} _t */
/** @typedef { ReturnType<_t> } TranslatedString */
/** @typedef { (selection: EditorSelection, nodes: Node[]) => TranslatedString } TranslatedStringGetter */

/**
 * @typedef {Object} ToolbarNamespace
 * @property {string} id
 * @property {(targetedNodes: Node[]) => boolean} isApplied
 * @typedef {Object} ToolbarGroup
 * @property {string} id
 * @property {string[]} [namespaces]
 * @typedef {ToolbarCommandItem | ToolbarComponentItem} ToolbarItem
 * @typedef {Object} ToolbarCommandItem
 * @property {string} id
 * @property {string} groupId
 * @property {string} commandId
 * @property {string[]} [namespaces]
 * @property {Object} [commandParams]
 * @property {TranslatedString | TranslatedStringGetter} [description]
 * @property {string} [icon]
 * @property {string} [text]
 * @property {(selection: EditorSelection) => boolean} [isAvailable]
 * @property {(selection: EditorSelection, nodes: Node[]) => boolean} [isActive]
 * @property {(selection: EditorSelection, nodes: Node[]) => boolean} [isDisabled]
 * @typedef {Object} ToolbarComponentItem
 * @property {string} id
 * @property {string} groupId
 * @property {string[]} [namespaces]
 * @property {TranslatedString | TranslatedStringGetter} [description]
 * @property {Function} Component
 * @property {Object} props
 * @property {(selection: EditorSelection) => boolean} [isAvailable]
 */

/**
 * @typedef {Object} ToolbarCommandButton
 * @property {string} id
 * @property {string} groupId
 * @property {TranslatedStringGetter} description
 * @property {Function} run
 * @property {string} [icon]
 * @property {string} [text]
 * @property {(selection: EditorSelection) => boolean} isAvailable
 * @property {(selection: EditorSelection, nodes: Node[]) => boolean} [isActive]
 * @property {(selection: EditorSelection, nodes: Node[]) => boolean} [isDisabled]
 * @typedef {Object} ToolbarComponentButton
 * @property {string} id
 * @property {string} groupId
 * @property {string[]} [namespaces]
 * @property {TranslatedStringGetter} description
 * @property {Function} Component
 * @property {Object} props
 * @property {(selection: EditorSelection) => boolean} isAvailable
 * @typedef {ToolbarCommandButton | ToolbarComponentButton} ToolbarButton
 */

export const DELAY_TOOLBAR_OPEN = 300;
const MIN_SIZE_FOR_COMPACT = 7;
export const DISABLED_NAMESPACE = "disabled";

/**
 * @typedef { Object } ToolbarShared
 * @property { ToolbarPlugin['getToolbarInfo'] } getToolbarInfo
 */

/**
 * @typedef {((namespace: string) => boolean)[]} can_display_toolbar
 * @typedef {((selectionData: SelectionData) => boolean)[]} collapsed_selection_toolbar_predicate
 * @typedef {ToolbarGroup[]} toolbar_groups
 * @typedef {ToolbarNamespace[]} toolbar_namespaces
 */

/**
 * @typedef {(ToolbarCommandItem | ToolbarComponentItem)[]} toolbar_items
 */

export class ToolbarPlugin extends Plugin {
    static id = "toolbar";
    static dependencies = ["overlay", "selection", "userCommand"];
    static shared = ["getToolbarInfo"];
    /** @type {import("plugins").EditorResources} */
    resources = {
        selectionchange_handlers: this.handleSelectionChange.bind(this),
        selection_leave_handlers: () => this.closeToolbar(),
        selection_enter_handlers: () => this.updateToolbar(),
        step_added_handlers: () => this.updateToolbar(),
        user_commands: {
            id: "expandToolbar",
            run: () => {
                this.isToolbarExpanded = true;
                this.updateToolbar();
            },
        },
        toolbar_groups: [
            withSequence(100, { id: "expand_toolbar", namespaces: ["compact"] }),
            withSequence(30, { id: "layout" }),
        ],
        toolbar_items: {
            id: "expand_toolbar",
            groupId: "expand_toolbar",
            commandId: "expandToolbar",
            description: _t("Expand toolbar"),
            icon: "oi-ellipsis-v",
        },
        toolbar_namespace_providers: [
            withSequence(100, (targetedNodes, editableSelection) =>
                this.isToolbarVisible(targetedNodes, editableSelection)
                    ? "compact"
                    : undefined,
            ),
        ],
    };

    setup() {
        const groupIds = new Set();
        for (const group of this.getResource("toolbar_groups")) {
            if (groupIds.has(group.id)) {
                throw new Error(`Duplicate toolbar group id: ${group.id}`);
            }
            groupIds.add(group.id);
        }
        this.buttonGroups = this.getButtonGroups();
        this.buttonsByNamespace = { DISABLED_NAMESPACE: [] };

        this.isMobileToolbar = hasTouch() && window.visualViewport;

        if (this.isMobileToolbar) {
            this.overlay = new MobileToolbarOverlay(this.editable);
        } else {
            this.overlay = this.dependencies.overlay.createOverlay(Toolbar, {
                positionOptions: {
                    position: "top-start",
                },
                closeOnPointerdown: false,
            });
        }
        this.state = reactive({ buttonGroups: [], namespace: undefined });

        this.onSelectionChangeActive = true;
        this.debouncedUpdateToolbar = debounce(this._updateToolbar, DELAY_TOOLBAR_OPEN);

        if (this.isMobileToolbar) {
            this.addDomListener(this.editable, "pointerup", () => {
                this.isToolbarExpanded = false;
            });
        } else {
            this.addDomListener(this.editable, "mousedown", (ev) => {
                this.closeToolbar(this.dependencies.selection.getSelectionData());
                this.debouncedUpdateToolbar.cancel();
                this.onSelectionChangeActive = false;
            });
            this.addGlobalDomListener("mouseup", (ev) => {
                if (ev.detail >= 2) {
                    this.onSelectionChangeActive = true;
                    this.debouncedUpdateToolbar();
                } else {
                    setTimeout(() => {
                        this.updateToolbar();
                        this.onSelectionChangeActive = true;
                    });
                }
            });

            this.addDomListener(this.editable, "keydown", (ev) => {
                if (ev.key?.startsWith("Arrow")) {
                    this.closeToolbar(this.dependencies.selection.getSelectionData());
                    this.onSelectionChangeActive = false;
                }
            });
            this.addDomListener(this.editable, "keyup", (ev) => {
                if (ev.key?.startsWith("Arrow")) {
                    this.onSelectionChangeActive = true;
                    this.debouncedUpdateToolbar();
                }
            });
        }
        this.isToolbarExpanded = false;
        this.toolbarProps = {
            class: "shadow rounded my-2",
            getSelection: () => this.dependencies.selection.getSelectionData(),
            focusEditable: () => this.dependencies.selection.focusEditable(),
            state: this.state,
        };
    }

    destroy() {
        this.debouncedUpdateToolbar?.cancel();
        this.updateToolbar?.cancel();
        this.overlay?.close();
        super.destroy();
    }

    /**
     * @returns {ToolbarButton[]}
     */
    getButtons() {
        /** @type {ToolbarItem[]} */
        const toolbarItems = this.getResource("toolbar_items");

        /** @type {(item: ToolbarCommandItem) => ToolbarCommandButton} */
        const commandItemToButton = (item) => {
            const command = this.dependencies.userCommand.getCommand(item.commandId);
            return composeToolbarButton(command, item);
        };
        /** @type {(item: ToolbarComponentItem) => ToolbarComponentButton} */
        const componentItemToButton = (item) => ({
            isAvailable: () => true,
            ...item,
            description:
                item.description instanceof Function
                    ? item.description
                    : () => item.description,
        });

        return toolbarItems.map((item) =>
            "Component" in item
                ? componentItemToButton(item)
                : commandItemToButton(item),
        );
    }

    getButtonGroups() {
        const buttons = this.getButtons();
        /** @type {ToolbarGroup[]} */
        const groups = this.getResource("toolbar_groups");

        return groups.map((group) => ({
            ...omit(group, "namespaces"),
            buttons: buttons
                .filter((button) => button.groupId === group.id)
                .map((button) => ({
                    ...button,
                    namespaces: button.namespaces || group.namespaces || ["expanded"],
                })),
        }));
    }

    /**
     * @returns {ToolbarButton[]}
     */
    getButtonsForNamespace(namespace) {
        if (this.buttonsByNamespace[namespace]) {
            return this.buttonsByNamespace[namespace];
        }
        const button = this.buttonGroups.flatMap((group) =>
            group.buttons.filter((btn) => btn.namespaces.includes(namespace)),
        );
        this.buttonsByNamespace[namespace] = button;
        return button;
    }

    getToolbarInfo() {
        return {
            buttonGroups: this.buttonGroups,
        };
    }

    handleSelectionChange(selectionData) {
        if (this.onSelectionChangeActive) {
            this.updateToolbar(selectionData);
        }
    }

    updateToolbar = debounce(this._updateToolbar, 0, { trailing: true });
    _updateToolbar(selectionData = this.dependencies.selection.getSelectionData()) {
        if (
            !selectionData.currentSelectionIsInEditable ||
            selectionData.documentSelectionIsProtected ||
            selectionData.documentSelectionIsProtecting
        ) {
            this.closeToolbar();
            return;
        }
        const targetedNodes = this.dependencies.selection.getTargetedNodes();
        if (
            targetedNodes.every(
                (node) => !this.dependencies.selection.isNodeEditable(node),
            )
        ) {
            this.closeToolbar();
            return;
        }
        let currentNamespace = null;
        const filteredtargetedNodes = this.getFilteredTargetedNodes(targetedNodes);
        for (const fn of this.getResource("toolbar_namespace_providers")) {
            currentNamespace = fn(
                filteredtargetedNodes,
                selectionData.editableSelection,
            );
            if (currentNamespace) {
                break;
            }
        }

        if (currentNamespace === DISABLED_NAMESPACE) {
            this.closeToolbar();
            return;
        }

        if (currentNamespace === "compact" && this.isToolbarExpanded) {
            currentNamespace = "expanded";
        }

        if (currentNamespace) {
            this.state.namespace = currentNamespace;
            if (!this.overlay.isOpen) {
                this.overlay.open({ props: this.toolbarProps });
            }
            this.updateButtonsStates(
                selectionData.editableSelection,
                filteredtargetedNodes,
            );
        } else {
            this.closeToolbar();
        }
    }

    getFilteredTargetedNodes(targetedNodes) {
        return targetedNodes
            .filter(
                (node) =>
                    this.dependencies.selection.isNodeEditable(node) &&
                    (node.nodeType !== Node.TEXT_NODE ||
                        (!isEmptyTextNode(node) && !isZWS(node))),
            )
            .filter((node) => {
                const element = closestElement(node);
                const style = this.document.defaultView.getComputedStyle(element);
                return style.display !== "none" && style.visibility !== "hidden";
            });
    }

    isToolbarVisible(targetedNodes, editableSelection) {
        if (this.isMobileToolbar) {
            return true;
        }

        const isCollapsed = editableSelection.isCollapsed;
        if (isCollapsed) {
            return false;
        }
        const selectionText = editableSelection.textContent();
        const textCleaned = selectionText.replace(/(\r\n|\n|\r|\u200B|\uFEFF)/gm, "");
        if (textCleaned.length) {
            return true;
        }
        return targetedNodes.some(
            (node) => node.nodeType === Node.ELEMENT_NODE && node.tagName === "BR",
        );
    }

    /**
     * @param {SelectionData} selectionData
     */
    closeToolbar(selectionData = null) {
        if (!this.overlay.isOpen) {
            return;
        }
        const anchor = selectionData?.documentSelectionIsInEditable
            ? selectionData.editableSelection?.anchorNode
            : document.getSelection()?.anchorNode;
        const shouldPreventClosing =
            anchor?.closest?.("[data-prevent-closing-overlay]")?.dataset
                ?.preventClosingOverlay === "true";
        if (!shouldPreventClosing) {
            this.overlay.close();
            this.isToolbarExpanded = false;
            this.state.namespace = null;
        }
    }

    /**
     * @param {EditorSelection} selection
     * @param {Node[]} targetedNodes
     */
    updateButtonsStates(selection, targetedNodes) {
        const availableButtons = this.getAvailableButtonsSet(selection);
        this.state.buttonGroups = this.buttonGroups
            .map((group) => ({
                id: group.id,
                buttons: group.buttons
                    .filter((button) => availableButtons.has(button))
                    .map((button) => ({
                        id: button.id,
                        description: button.description(selection, targetedNodes),
                        isDisabled: !!button.isDisabled?.(selection, targetedNodes),
                        ...(button.Component
                            ? pick(button, "Component", "props")
                            : {
                                  ...pick(button, "run", "icon", "text"),
                                  isActive: !!button.isActive?.(
                                      selection,
                                      targetedNodes,
                                  ),
                              }),
                    })),
            }))
            .filter((group) => group.buttons.length > 0);
    }

    /**
     * @param {EditorSelection} selection
     * @returns {Set<ToolbarButton>}
     */
    getAvailableButtonsSet(selection) {
        if (this.state.namespace === "compact") {
            return this.getAvailableButtonsCompact(selection);
        }
        const isAvailable = (button) => button.isAvailable(selection);
        return new Set(
            this.getButtonsForNamespace(this.state.namespace).filter(isAvailable),
        );
    }

    /**
     * @param {EditorSelection} selection
     * @returns {Set<ToolbarButton>}
     */
    getAvailableButtonsCompact(selection) {
        const isAvailable = memoize((button) => button.isAvailable(selection));
        const compact = this.getButtonsForNamespace("compact").filter(isAvailable);
        const expanded = this.getButtonsForNamespace("expanded").filter(isAvailable);
        const shouldDisplayCompactToolbar =
            expanded.length >= MIN_SIZE_FOR_COMPACT &&
            expanded.length > compact.length;
        if (shouldDisplayCompactToolbar) {
            return new Set(compact);
        }
        this.state.namespace = "expanded";
        return new Set(expanded);
    }
}

class MobileToolbarOverlay {
    constructor(editable) {
        this.isOpen = false;
        this.overlayId = `mobile_toolbar_${Math.random().toString(16).slice(2)}`;
        this.editable = editable;
    }

    open({ props }) {
        props.class = "shadow";
        props.editable = this.editable;
        if (!this.isOpen) {
            const modal = this.editable.closest(".o_modal_full");
            if (modal) {
                modal.style.paddingBottom = "40px";
            }
            registry.category("main_components").add(this.overlayId, {
                Component: ToolbarMobile,
                props,
            });
            this.isOpen = true;
        }
    }

    close() {
        if (!this.isOpen) {
            return;
        }
        const modal = this.editable.closest(".o_modal_full");
        if (modal) {
            modal.style.paddingBottom = "";
        }
        registry.category("main_components").remove(this.overlayId);
        this.isOpen = false;
    }
}
