/** @odoo-module native */
import { useRef } from "@odoo/owl";
import { useEmojiPicker } from "@web/components/emoji_picker/emoji_picker";
/**
 * @param {typeof import("@odoo/owl").Component} T
 * @returns {typeof T}
 */
export const EmojisFieldCommon = (T) =>
    class EmojisFieldCommon extends T {
        _setupOverride() {
            this.emojiPicker = useEmojiPicker(
                useRef("emojisButton"),
                {
                    /** @param {string} codepoints */
                    onSelect: (codepoints) => {
                        const originalContent = this.targetEditElement.el.value;
                        const start = this.targetEditElement.el.selectionStart;
                        const end = this.targetEditElement.el.selectionEnd;
                        const left = originalContent.slice(0, start);
                        const right = originalContent.slice(
                            end,
                            originalContent.length,
                        );
                        this.targetEditElement.el.value = left + codepoints + right;
                        this.targetEditElement.el.dispatchEvent(
                            new InputEvent("input"),
                        );
                        this.targetEditElement.el.dispatchEvent(
                            new KeyboardEvent("keydown"),
                        );
                        this.targetEditElement.el.focus();
                        const newCursorPos = start + codepoints.length;
                        this.targetEditElement.el.setSelectionRange(
                            newCursorPos,
                            newCursorPos,
                        );
                        if (this._emojiAdded) {
                            this._emojiAdded();
                        }
                    },
                },
                {
                    position: "bottom",
                },
            );
        }
    };
