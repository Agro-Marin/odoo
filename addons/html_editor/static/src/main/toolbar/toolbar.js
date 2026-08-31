/** @odoo-module native */
import { trapFocus } from "@html_editor/utils/dom_traversal";
import { Component, useRef, useState, validate } from "@odoo/owl";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";
import { omit, pick } from "@web/core/utils/collections/objects";

export class Toolbar extends Component {
    static template = "html_editor.Toolbar";
    static props = {
        class: { type: String, optional: true },
        getSelection: Function,
        focusEditable: Function,
        state: {
            type: Object,
            shape: {
                namespace: { type: String, optional: true },
                buttonGroups: {
                    type: Array,
                    element: {
                        type: Object,
                        shape: {
                            id: String,
                            buttons: {
                                type: Array,
                                element: {
                                    type: Object,
                                    validate: (button) => {
                                        const base = {
                                            id: String,
                                            description: String,
                                            isDisabled: Boolean,
                                        };
                                        if (button.Component) {
                                            validate(button, {
                                                ...base,
                                                Component: Function,
                                                props: { type: Object, optional: true },
                                            });
                                        } else {
                                            validate(button, {
                                                ...base,
                                                run: Function,
                                                icon: { type: String, optional: true },
                                                text: { type: String, optional: true },
                                                isActive: Boolean,
                                            });
                                        }
                                        return true;
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    };

    setup() {
        this.state = useState(this.props.state);
        this.toolbarEl = useRef("toolbarEl");

        // Alt+F reaches the toolbar from the editable. It must not fire while
        // focus is already inside a toolbar or an overlay of its own.
        const isOutsideToolbar = () =>
            !document.activeElement.closest(
                ".o-we-toolbar[data-namespace], [data-prevent-closing-overlay]",
            );
        useHotkey("alt+f", () => this.focusFirstToolbarButton(), {
            bypassEditableProtection: true,
            withOverlay: () => (isOutsideToolbar() ? this.toolbarEl.el : null),
            isAvailable: isOutsideToolbar,
        });
    }

    focusFirstToolbarButton() {
        this.toolbarEl.el?.querySelector("button:not([disabled])")?.focus();
    }

    onKeyDown(ev) {
        if (ev.target.closest(".dropdown.show")) {
            // An open dropdown owns the keyboard.
            return;
        }
        if (["Tab", "ArrowLeft", "ArrowRight"].includes(ev.key)) {
            ev.preventDefault();
            ev.stopPropagation();
            const isBackward =
                ev.key === "ArrowLeft" || (ev.key === "Tab" && ev.shiftKey);
            trapFocus(this.toolbarEl.el.querySelectorAll("button"), isBackward);
        } else if (ev.key === "Escape") {
            ev.stopPropagation();
            this.props.focusEditable();
        }
    }

    onButtonClick(button) {
        button.run();
        this.props.focusEditable();
    }
}

export const toolbarButtonProps = {
    title: [String, Function],
    getSelection: Function,
    isDisabled: Boolean,
};

/** @typedef {import("@html_editor/core/user_command_plugin").UserCommand} UserCommand */
/** @typedef {import("./toolbar_plugin").ToolbarCommandItem} ToolbarCommandItem */
/** @typedef {import("./toolbar_plugin").ToolbarCommandButton} ToolbarCommandButton */

/**
 * @param {UserCommand} userCommand
 * @param {ToolbarCommandItem} toolbarItem
 * @returns {ToolbarCommandButton}
 */
export function composeToolbarButton(userCommand, toolbarItem) {
    const description = toolbarItem.description || userCommand.description;
    return {
        ...pick(userCommand, "icon"),
        ...omit(toolbarItem, "commandId", "commandParams"),
        run: () => userCommand.run(toolbarItem.commandParams),
        isAvailable: (selection) =>
            [userCommand.isAvailable, toolbarItem.isAvailable]
                .filter(Boolean)
                .every((predicate) => predicate(selection)),
        description: description instanceof Function ? description : () => description,
    };
}
