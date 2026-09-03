/** @odoo-module native */
import { useSelection } from "@mail/utils/common/hooks";
import { Component, useRef } from "@odoo/owl";
import { useEmojiPicker } from "@web/components/emoji_picker";
import { isEventHandled } from "@web/core/utils/dom/events";
import { useAutofocus, useService } from "@web/core/utils/hooks";

/**
 * One editable option row of the "Create a poll" dialog.
 *
 * @typedef {Object} Props
 * @property {{ label: string, start?: number, end?: number, direction?: string }} model
 * @property {boolean} deletable
 * @property {() => void} onClickRemove
 * @extends {Component<Props, import("@web/env").OdooEnv>}
 */
export class CreatePollOption extends Component {
    static template = "mail.CreatePollOption";
    static props = ["model", "onClickRemove", "deletable"];

    setup() {
        super.setup();
        this.pickerRef = useRef("picker");
        this.ui = useService("ui");
        this.selection = useSelection({
            refName: "root",
            model: this.props.model,
            /** @param {MouseEvent} ev */
            preserveOnClickAwayPredicate: async (ev) => {
                await new Promise(setTimeout);
                return (
                    isEventHandled(ev, "emoji.selectEmoji") ||
                    Boolean(this.pickerRef.el?.contains(ev.target))
                );
            },
        });
        this.inputRef = useAutofocus({ refName: "root" });
        useEmojiPicker(this.pickerRef, {
            /** @param {string} str */
            onSelect: (str) => {
                const label = this.props.model.label;
                const firstPart = label.slice(0, this.props.model.start);
                const secondPart = label.slice(this.props.model.end, label.length);
                this.props.model.label = firstPart + str + secondPart;
                this.selection.moveCursor((firstPart + str).length);
                if (!this.ui.isSmall) {
                    this.inputRef.el?.focus();
                }
            },
        });
    }
}
