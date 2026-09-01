/** @odoo-module native */
import { isHtmlContentSupported } from "@html_editor/core/selection_plugin";
import { Plugin } from "@html_editor/plugin";
import { closestBlock } from "@html_editor/utils/blocks";
import { fillEmpty, fillShrunkPhrasingParent } from "@html_editor/utils/dom";
import {
    closestElement,
    descendants,
    selectElements,
} from "@html_editor/utils/dom_traversal";
import { parseHTML } from "@html_editor/utils/html";
import { withSequence } from "@html_editor/utils/resource";
import { htmlEscape } from "@odoo/owl";
import { _t } from "@web/core/translation";

import { isEmptyBlock, isParagraphRelatedElement } from "../utils/dom_info.js";

// `bannerType` comes first so a command can bind it: `.bind(this, "info")`.
function checkCommandAvailablePredicates(bannerType, selection) {
    return this.getResource("banner_command_available_predicates").every(
        (predicateFn) => predicateFn(selection, bannerType),
    );
}

/**
 * @typedef { Object } BannerShared
 * @property { BannerPlugin['insertBanner'] } insertBanner
 */

export class BannerPlugin extends Plugin {
    static id = "banner";
    static dependencies = [
        "baseContainer",
        "history",
        "dom",
        "emoji",
        "selection",
        "sanitize",
    ];
    static shared = ["insertBanner"];
    /** @type {import("plugins").EditorResources} */
    resources = {
        user_commands: [
            {
                id: "banner_info",
                title: _t("Banner Info"),
                description: _t("Insert an info banner"),
                icon: "fa-info-circle",
                isAvailable: checkCommandAvailablePredicates.bind(this, "info"),
                run: () => {
                    this.insertBanner(_t("Banner Info"), "💡", "info");
                },
            },
            {
                id: "banner_success",
                title: _t("Banner Success"),
                description: _t("Insert a success banner"),
                icon: "fa-check-circle",
                isAvailable: checkCommandAvailablePredicates.bind(this, "success"),
                run: () => {
                    this.insertBanner(_t("Banner Success"), "✅", "success");
                },
            },
            {
                id: "banner_warning",
                title: _t("Banner Warning"),
                description: _t("Insert a warning banner"),
                icon: "fa-exclamation-triangle",
                isAvailable: checkCommandAvailablePredicates.bind(this, "warning"),
                run: () => {
                    this.insertBanner(_t("Banner Warning"), "⚠️", "warning");
                },
            },
            {
                id: "banner_danger",
                title: _t("Banner Danger"),
                description: _t("Insert a danger banner"),
                icon: "fa-exclamation-circle",
                isAvailable: checkCommandAvailablePredicates.bind(this, "danger"),
                run: () => {
                    this.insertBanner(_t("Banner Danger"), "❌", "danger");
                },
            },
            {
                id: "banner_monospace",
                title: _t("Monospace"),
                description: _t("Insert a monospace banner"),
                icon: "fa-laptop",
                isAvailable: checkCommandAvailablePredicates.bind(this, "secondary"),
                run: () => {
                    this.insertBanner(
                        _t("Monospace Banner"),
                        undefined,
                        "secondary",
                        "font-monospace",
                    );
                },
            },
        ],
        banner_command_available_predicates: (selection, bannerType) =>
            isHtmlContentSupported(selection) &&
            // Only the banner's OWN type is hidden: from inside a banner the
            // other four switch it in place.
            !closestElement(
                selection.anchorNode,
                `.o_editor_banner.alert-${bannerType}`,
            ),
        powerbox_categories: withSequence(20, { id: "banner", name: _t("Banner") }),
        powerbox_items: [
            {
                commandId: "banner_info",
                categoryId: "banner",
            },
            {
                commandId: "banner_success",
                categoryId: "banner",
            },
            {
                commandId: "banner_warning",
                categoryId: "banner",
            },
            {
                commandId: "banner_danger",
                categoryId: "banner",
            },
            {
                commandId: "banner_monospace",
                categoryId: "banner",
            },
        ],
        normalize_handlers: withSequence(
            5,
            this.handle_monospace_tab_to_spaces.bind(this),
        ),
        power_buttons_visibility_predicates: ({ anchorNode }) =>
            !closestElement(anchorNode, ".o_editor_banner"),
        move_node_blacklist_selectors: ".o_editor_banner *",
        move_node_whitelist_selectors: ".o_editor_banner",

        delete_backward_overrides: this.handleDeleteBackward.bind(this),
        delete_backward_word_overrides: this.handleDeleteBackward.bind(this),
        shift_tab_overrides: this.handleShiftTab.bind(this),
    };

    setup() {
        this.addDomListener(this.editable, "click", (e) => {
            if (e.target.classList.contains("o_editor_banner_icon")) {
                this.onBannerEmojiChange(e.target);
            }
        });
    }

    insertBanner(title, emoji, alertClass, containerClass = "", contentClass = "") {
        containerClass = containerClass ? `${containerClass} ` : "";
        contentClass = contentClass ? `${contentClass} ` : "";

        const bannerClasses = `${containerClass}o_editor_banner user-select-none o-contenteditable-false ${
            emoji ? "lh-1 " : ""
        }d-flex align-items-center alert alert-${alertClass} pb-0 pt-3 ps-3 pe-3`;
        const bannerContentClasses = `${contentClass}o_editor_banner_content o-contenteditable-true w-100 px-3`;
        const emojiHtml = emoji
            ? `<i class="o_editor_banner_icon mb-3 fst-normal" data-oe-aria-label="${htmlEscape(
                  title,
              )}">${htmlEscape(emoji)}</i>`
            : "";

        const selection = this.dependencies.selection.getEditableSelection();
        // Inside a banner already: restyle it in place rather than nest one.
        const currentBanner = closestElement(selection.anchorNode, ".o_editor_banner");
        if (currentBanner) {
            currentBanner.className = bannerClasses;
            currentBanner.querySelector(".o_editor_banner_content").className =
                bannerContentClasses;
            const icon = currentBanner.querySelector(".o_editor_banner_icon");
            if (emojiHtml) {
                const newIcon = parseHTML(this.document, emojiHtml).firstChild;
                icon ? icon.replaceWith(newIcon) : currentBanner.prepend(newIcon);
            } else {
                icon?.remove();
            }
            this.dependencies.history.addStep();
            return;
        }

        const blockEl = closestBlock(selection.anchorNode);
        let baseContainer;
        if (isParagraphRelatedElement(blockEl)) {
            baseContainer = this.document.createElement(blockEl.nodeName);
            baseContainer.append(...blockEl.childNodes);
        } else if (blockEl.nodeName === "LI") {
            baseContainer = this.dependencies.baseContainer.createBaseContainer();
            baseContainer.append(...blockEl.childNodes);
            fillShrunkPhrasingParent(blockEl);
        } else {
            baseContainer = this.dependencies.baseContainer.createBaseContainer();
            fillShrunkPhrasingParent(baseContainer);
        }
        const baseContainerHtml = baseContainer.outerHTML;
        const bannerElement = parseHTML(
            this.document,
            `<div class="${bannerClasses}" data-oe-role="status">
                ${emojiHtml}
                <div class="${bannerContentClasses}">
                    ${baseContainerHtml}
                </div>
            </div>`,
        ).childNodes[0];
        this.dependencies.dom.insert(bannerElement);
        this.dependencies.selection.setCursorEnd(
            bannerElement.querySelector(
                `.o_editor_banner_content > ${baseContainer.tagName}`,
            ),
        );
        this.dependencies.history.addStep();
    }

    onBannerEmojiChange(iconElement) {
        this.dependencies.emoji.showEmojiPicker({
            target: iconElement,
            onSelect: (emoji) => {
                iconElement.textContent = emoji;
                this.dependencies.history.addStep();
            },
        });
    }

    handleDeleteBackward(range) {
        const editorBannerContent = closestElement(
            range.endContainer,
            ".o_editor_banner_content",
        );
        if (!isEmptyBlock(editorBannerContent)) {
            return;
        }
        const bannerElement = closestElement(editorBannerContent, ".o_editor_banner");
        const baseContainer = this.dependencies.baseContainer.createBaseContainer();
        fillEmpty(baseContainer);
        bannerElement.replaceWith(baseContainer);
        this.dependencies.selection.setCursorStart(baseContainer);
        return true;
    }

    handle_monospace_tab_to_spaces(root) {
        for (const el of selectElements(
            root,
            ".font-monospace.o_editor_banner .oe-tabs",
        )) {
            const spacesElement = document.createTextNode("\u00A0\u00A0\u00A0\u00A0");
            el.replaceWith(spacesElement);
        }
    }

    handleShiftTab() {
        const selection = this.dependencies.selection.getEditableSelection();
        const monospaceBannerElement = closestElement(
            selection.anchorNode,
            ".font-monospace.o_editor_banner",
        );
        if (!monospaceBannerElement) {
            return;
        }
        const fourSpacesRe = /^(?:\u200B*\s\u200B*){4}/;
        for (const block of [...this.dependencies.selection.getTargetedBlocks()]) {
            const text = block.textContent;
            if (text.match(fourSpacesRe)) {
                const textNode = descendants(block).find(
                    (n) =>
                        n.nodeType === Node.TEXT_NODE &&
                        n.textContent.length &&
                        n.textContent !== "\u200b",
                );
                if (textNode) {
                    textNode.textContent = textNode.textContent.replace(
                        fourSpacesRe,
                        "",
                    );
                }
            }
        }
    }
}
