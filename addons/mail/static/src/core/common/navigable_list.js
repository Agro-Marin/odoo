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
        onExternalClick(
            "root",
            /** @param {MouseEvent} ev */ async (ev) => {
                await new Promise((resolve) => browser.setTimeout(resolve));
                if (isEventHandled(ev, "composer.onClickTextarea")) {
                    return;
                }
                this.close();
            },
        );
        usePosition("root", () => this.props.anchorRef, {
            position: this.props.position,
        });
        useEffect(
            () => {
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
                    browser.clearTimeout(this.loadingTimeoutId);
                    this.loadingTimeoutId = undefined;
                    this.state.showLoading = false;
                } else if (!this.loadingTimeoutId) {
                    this.loadingTimeoutId = browser.setTimeout(
                        () => (this.state.showLoading = true),
                        2000,
                    );
                }
                return () => browser.clearTimeout(this.loadingTimeoutId);
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
        return [...this.props.options].sort(
            /**
             * @param {Object} o1
             * @param {Object} o2
             */
            (o1, o2) => (o1.group ?? 0) - (o2.group ?? 0),
        );
    }

    /**
     * @param {Object} option
     * @returns {string}
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
     * @param {boolean} [force]
     */
    close(force = false) {
        if (force || this.props.closeOnSelect) {
            this.state.open = false;
            this.state.activeIndex = null;
        }
    }

    /**
     * @param {Event} ev
     * @param {number} index
     * @param {Object} [params={}]
     */
    selectOption(ev, index, params = {}) {
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

    /** @param {"first"|"last"|"previous"|"next"} direction */
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

    /** @param {KeyboardEvent} ev */
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

    /** @param {number} index */
    onOptionMouseEnter(index) {
        this.state.activeIndex = index;
    }
}
