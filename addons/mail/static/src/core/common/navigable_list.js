/** @odoo-module native */
import { ImStatus } from "@mail/core/common/im_status";
import { onExternalClick } from "@mail/utils/common/hooks";
import { Component, useEffect, useExternalListener, useRef, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { getActiveHotkey } from "@web/core/browser/hotkeys";
import { usePosition } from "@web/core/position/position_hook";
import { isEventHandled, markEventHandled } from "@web/core/utils/dom/events";
import { useService } from "@web/core/utils/hooks";
export class NavigableList extends Component {
    static components = { ImStatus };
    static template = "mail.NavigableList";
    static props = {
        anchorRef: { optional: true },
        class: { type: String, optional: true },
        onSelect: { type: Function },
        options: { type: Array },
        optionTemplate: { type: String, optional: true },
        position: { type: String, optional: true },
        closeOnSelect: { type: Boolean, optional: true },
        isLoading: { type: Boolean, optional: true },
    };
    static defaultProps = {
        position: "bottom",
        closeOnSelect: true,
        isLoading: false,
    };

    setup() {
        super.setup();
        this.rootRef = useRef("root");
        this.state = useState({
            activeIndex: null,
            open: false,
            showLoading: false,
        });
        this.hotkey = useService("hotkey");
        this.hotkeysToRemove = [];

        useExternalListener(window, "keydown", this.onKeydown, true);
        onExternalClick("root", async (ev) => {
            // Let event be handled by bubbling handlers first. Routed through
            // `browser` so tests can mock time.
            await new Promise((resolve) => browser.setTimeout(resolve));
            if (isEventHandled(ev, "composer.onClickTextarea")) {
                return;
            }
            // no force: embedded closeOnSelect=false lists (e.g. livechat tag
            // edit) sit next to their search input, and a click on it must
            // not hide them.
            this.close();
        });
        // position and size
        usePosition("root", () => this.props.anchorRef, {
            position: this.props.position,
        });
        useEffect(
            () => {
                // Only (re)open — which resets the keyboard selection — when
                // the displayed option set actually changes. Depending on
                // props identity re-ran this on every parent render: arrow-key
                // selection was yanked back to the first item whenever an
                // unrelated re-render happened (e.g. a fetch flag flip), and
                // Escape-dismissed lists were resurrected.
                const optionsKey = this.props.options
                    .map((option) => this.getOptionKey(option))
                    .join("\x00");
                if (optionsKey !== this.lastOptionsKey) {
                    this.lastOptionsKey = optionsKey;
                    this.open();
                }
            },
            () => [this.props.options, this.props.isLoading],
        );
        useEffect(
            () => {
                if (!this.props.isLoading) {
                    clearTimeout(this.loadingTimeoutId);
                    // Reset the id, otherwise the `!this.loadingTimeoutId`
                    // guard below stays false forever and the spinner never
                    // re-arms on later loading cycles of the same instance.
                    this.loadingTimeoutId = undefined;
                    this.state.showLoading = false;
                } else if (!this.loadingTimeoutId) {
                    this.loadingTimeoutId = setTimeout(
                        () => (this.state.showLoading = true),
                        2000,
                    );
                }
            },
            () => [this.props.isLoading],
        );
    }

    get show() {
        return Boolean(
            this.state.open && (this.props.isLoading || this.props.options.length),
        );
    }

    get sortedOptions() {
        // Copy before sorting: Array.sort mutates in place, and props.options
        // is parent-owned (often a reactive/store array) — reordering it from a
        // render getter corrupts the parent's order and can trigger re-renders.
        return [...this.props.options].sort(
            (o1, o2) => (o1.group ?? 0) - (o2.group ?? 0),
        );
    }

    /**
     * Identity of an option, to detect actual changes of the option set:
     * option objects are re-created literals on every parent render, so
     * object identity cannot be used.
     */
    getOptionKey(option) {
        const record =
            option.partner ?? option.role ?? option.thread ?? option.cannedResponse;
        return `${record?.id ?? option.emoji?.codepoints ?? ""}-${option.label}`;
    }

    open() {
        this.state.open = true;
        this.state.activeIndex = null;
        this.navigate("first");
    }

    /**
     * @param {boolean} [force] close even when `closeOnSelect` is false —
     *  for explicit dismissals (Escape), otherwise such lists are
     *  undismissable.
     */
    close(force = false) {
        if (force || this.props.closeOnSelect) {
            this.state.open = false;
            this.state.activeIndex = null;
        }
    }

    selectOption(ev, index, params = {}) {
        // indexes handed out by the template/keyboard refer to the displayed
        // (sorted) order, not to props.options' order.
        const option = this.sortedOptions[index];
        if (!option) {
            return;
        }
        if (option.unselectable) {
            this.close();
            return;
        }
        this.props.onSelect(ev, option, {
            ...params,
        });
        this.close();
    }

    navigate(direction) {
        if (this.props.options.length === 0) {
            return;
        }
        const activeOptionId =
            this.state.activeIndex !== null ? this.state.activeIndex : 0;
        let targetId;
        switch (direction) {
            case "first":
                targetId = 0;
                break;
            case "last":
                targetId = this.props.options.length - 1;
                break;
            case "previous":
                targetId = activeOptionId - 1;
                if (targetId < 0) {
                    this.navigate("last");
                    return;
                }
                break;
            case "next":
                targetId = activeOptionId + 1;
                if (targetId > this.props.options.length - 1) {
                    this.navigate("first");
                    return;
                }
                break;
            default:
                return;
        }
        this.state.activeIndex = targetId;
    }

    onKeydown(ev) {
        if (!this.show) {
            return;
        }
        const hotkey = getActiveHotkey(ev);
        switch (hotkey) {
            case "enter":
                markEventHandled(ev, "NavigableList.select");
                if (this.state.activeIndex === null) {
                    this.close();
                    return;
                }
                this.selectOption(ev, this.state.activeIndex);
                break;
            case "escape":
                markEventHandled(ev, "NavigableList.close");
                this.close(true);
                break;
            case "tab":
                this.navigate(this.state.activeIndex === null ? "first" : "next");
                break;
            case "arrowup":
                this.navigate(this.state.activeIndex === null ? "first" : "previous");
                break;
            case "arrowdown":
                this.navigate(this.state.activeIndex === null ? "first" : "next");
                break;
            default:
                return;
        }
        if (this.props.options.length !== 0) {
            ev.stopPropagation();
        }
        ev.preventDefault();
    }

    onOptionMouseEnter(index) {
        // keep pointer and keyboard coherent: Enter inserts the active
        // option, so hovering must move the active index — otherwise the
        // hover styling suggests one option while Enter inserts another
        this.state.activeIndex = index;
    }
}
