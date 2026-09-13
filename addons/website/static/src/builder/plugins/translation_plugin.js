/** @odoo-module native */
import { Plugin } from "@html_editor/plugin";
import { makeContentsInline, unwrapContents } from "@html_editor/utils/dom";
import { withSequence } from "@html_editor/utils/resource";
import { makeLogger } from "@web/core/debug/debug_logger";
import { _t } from "@web/core/translation";

import { AttributeTranslateDialog } from "../translation_components/attributeTranslateDialog.js";
import { SelectTranslateDialog } from "../translation_components/selectTranslateDialog.js";

const log = makeLogger("website.builder.translation.translation_plugin");

/**
 * @typedef {((editableEls: HTMLElement[]) => void)[]} mark_translatable_nodes
 */

export const translationAttributeSelector =
    '[placeholder*="data-oe-translation-source-sha="], ' +
    '[title*="data-oe-translation-source-sha="], ' +
    '[value*="data-oe-translation-source-sha="], ' +
    '[alt*="data-oe-translation-source-sha="]';

export function getTranslationAttributeEls(rootEl) {
    const translationSavableEls = rootEl.querySelectorAll(translationAttributeSelector);
    const textAreaEls = Array.from(rootEl.querySelectorAll("textarea")).filter((el) =>
        el.textContent.includes("data-oe-translation-source-sha"),
    );
    return Array.from(translationSavableEls).concat(textAreaEls);
}

/**
 * @param {HTMLElement} containerEl
 * @returns {HTMLElement[]}
 */
function findOEditable(containerEl) {
    const isOEditable = (node) => {
        if (
            node.isContentEditable ||
            (node.classList.contains("o_editable_attribute") &&
                (!node.closest(".o_not_editable") ||
                    node.classList.contains("o_editable_media")))
        ) {
            return true;
        }
        return false;
    };
    const allDescendantEls = containerEl.querySelectorAll("*");
    return Array.from(allDescendantEls).filter(isOEditable);
}

export class TranslationPlugin extends Plugin {
    static id = "translation";
    static dependencies = ["history"];

    /** @type {import("plugins").WebsiteResources} */
    resources = {
        clean_for_save_handlers: this.cleanForSave.bind(this),
        get_dirty_els: this.getDirtyTranslations.bind(this),
        after_setup_editor_handlers: () => {
            const endSetupScan = log.perf(
                "after_setup_editor mark editable attributes",
            );
            const translationSavableEls = getTranslationAttributeEls(
                this.services.website.pageDocument,
            );
            for (const translationSavableEl of translationSavableEls) {
                translationSavableEl.classList.add("o_editable_attribute");
            }
            const editableElSelector = ".o_editable, .o_editable_attribute";
            const editableEls = [
                ...translationSavableEls,
                ...this.services.website.pageDocument.querySelectorAll(".o_editable"),
            ];
            for (const editableEl of editableEls) {
                if (editableEl.querySelectorAll(editableElSelector).length) {
                    editableEl.setAttribute("data-oe-readonly", "true");
                    editableEl.classList.remove("o_editable", "o_editable_attribute");
                }
            }
            endSetupScan(() => ({
                savableAttributes: translationSavableEls.length,
                editables: editableEls.length,
            }));
            return true;
        },
        start_edition_handlers: withSequence(5, () => {
            this.prepareTranslation();
        }),
        system_classes: ["o_editable_attribute"],
        before_insert_processors: withSequence(20, (container) => {
            log.pipeline("before_insert_processors: inline and unwrap", () => ({
                children: container.childElementCount,
            }));
            makeContentsInline(container);
            for (const el of container.querySelectorAll(this.nonTranslatedSelector)) {
                unwrapContents(el);
            }
            return container;
        }),
    };

    setup() {
        this.websiteService = this.services.website;
        this.notificationService = this.services.notification;
        this.dialogService = this.services.dialog;
        this.nonTranslatedSelector =
            `:not(${this.config.translatedElements.join(", ")})` +
            `:not(.o_translate_inline)`;
        log.lifecycle("setup", () => ({
            translatedElements: this.config.translatedElements.length,
        }));
    }

    prepareTranslation() {
        const endPrepare = log.perf("prepareTranslation");
        this.editableEls = findOEditable(this.editable);
        log.pipeline("prepareTranslation: found editables", () => ({
            editables: this.editableEls.length,
        }));
        this.buildTranslationInfoMap(this.editableEls);
        this.handleSelectTranslation(this.editableEls);
        this.markTranslatableNodes();
        log.pipeline("prepareTranslation: translation info built", () => ({
            translated: this.elToTranslationInfoMap.size,
            selectOptions: this.translateSelectEls.length,
        }));
        for (const [translatedEl] of this.elToTranslationInfoMap) {
            if (
                translatedEl.matches("input[type=hidden].o_translatable_input_hidden")
            ) {
                translatedEl.setAttribute("type", "text");
            }
        }

        const menuEls =
            this.websiteService.pageDocument.querySelectorAll(".dropdown-menu");
        for (const menuEl of menuEls) {
            this.addDomListener(menuEl, "click", (ev) => {
                const editableEl = ev.target.closest(".o_editable");
                if (editableEl && menuEl.contains(editableEl)) {
                    ev.stopPropagation();
                    ev.preventDefault();
                }
            });
        }

        const showNotification = (ev) => {
            if (ev.__shownNotification) {
                log.logic("showNotification: already shown for this event");
                return;
            }
            ev.__shownNotification = true;
            let message = _t("This translation is not editable.");
            if (ev.target.closest(".s_table_of_content_navbar_wrap")) {
                log.logic("showNotification: table of content navbar");
                message = _t(
                    "Translate header in the text. Menu is generated automatically.",
                );
            }
            this.notificationService.add(message, {
                type: "info",
                sticky: false,
            });
        };
        for (const translateEl of this.editableEls) {
            this.handleToC(translateEl);
        }
        const savableInsideNotEditableEls = this.editable.querySelectorAll(
            ".o_not_editable .o_editable, .o_not_editable .o_editable_attribute",
        );
        for (const savableInsideNotEditableEl of savableInsideNotEditableEls) {
            this.addDomListener(savableInsideNotEditableEl, "click", showNotification);
        }
        log.pipeline("prepareTranslation: listeners attached", () => ({
            menus: menuEls.length,
            savableInsideNotEditable: savableInsideNotEditableEls.length,
        }));
        this.originalElToTranslationInfoMap = new Map();
        for (const [translateEl, translationInfo] of this.elToTranslationInfoMap) {
            this.originalElToTranslationInfoMap.set(
                translateEl,
                JSON.parse(JSON.stringify(translationInfo)),
            );
        }
        endPrepare(() => ({
            snapshot: this.originalElToTranslationInfoMap.size,
        }));
    }

    /**
     * @param {HTMLElement[]} editableEls
     */
    buildTranslationInfoMap(editableEls) {
        this.elToTranslationInfoMap = new Map();
        const translatedAttrs = ["placeholder", "title", "alt", "value"];
        const translationRegex =
            /<span [^>]*data-oe-translation-source-sha="([^"]+)"[^>]*>(.*)<\/span>/;
        const isEmpty = (el) => !el.hasChildNodes() || el.innerHTML.trim() === "";
        const matchTag = (el) => el.matches("input, select, textarea, img");
        for (const translatedAttr of translatedAttrs) {
            const filteredEditableEls = editableEls.filter(
                (editableEl) =>
                    editableEl.hasAttribute(translatedAttr) &&
                    editableEl
                        .getAttribute(translatedAttr)
                        .includes("data-oe-translation-source-sha=") &&
                    (isEmpty(editableEl) || matchTag(editableEl)),
            );
            for (const filteredEditableEl of filteredEditableEls) {
                const translation = filteredEditableEl.getAttribute(translatedAttr);
                this.updateTranslationMap(
                    filteredEditableEl,
                    translation,
                    translatedAttr,
                );
                const match = translation.match(translationRegex);
                if (match) {
                    filteredEditableEl.setAttribute(translatedAttr, match[2]);
                    if (translatedAttr === "value") {
                        filteredEditableEl.value = match[2];
                    }
                }
                filteredEditableEl.classList.add("o_translatable_attribute");
            }
        }
        const textEditEls = editableEls.filter(
            (editableEl) =>
                editableEl.matches("textarea") &&
                editableEl.textContent.includes("data-oe-translation-source-sha"),
        );
        for (const textEditEl of textEditEls) {
            const translation = textEditEl.textContent;
            this.updateTranslationMap(textEditEl, translation, "textContent");
            const match = translation.match(translationRegex);
            if (match) {
                textEditEl.value = match[2];
                textEditEl.innerText = match[2];
            }
            textEditEl.classList.add("o_translatable_text");
            textEditEl.classList.remove("o_text_content_invisible");
        }
        log.pipeline("buildTranslationInfoMap", () => ({
            editables: editableEls.length,
            textareas: textEditEls.length,
            translated: this.elToTranslationInfoMap.size,
        }));
    }

    handleSelectTranslation(editableEls) {
        const selectEls = editableEls.filter((editableEl) =>
            editableEl.matches("[data-oe-translation-source-sha] > select"),
        );
        this.translateSelectEls = [];
        for (const selectEl of selectEls) {
            const selectTranslationEl = document.createElement("div");
            selectTranslationEl.className = "o_translation_select";
            const optionNames = [...selectEl.options].map((option) => option.text);
            for (const optionName of optionNames) {
                const optionEl = document.createElement("div");
                optionEl.textContent = optionName;
                optionEl.dataset.initialTranslationValue = optionName;
                optionEl.className = "o_translation_select_option";
                selectTranslationEl.appendChild(optionEl);
                this.translateSelectEls.push(optionEl);
            }
            selectEl.before(selectTranslationEl);
        }
        log.pipeline("handleSelectTranslation", () => ({
            selects: selectEls.length,
            options: this.translateSelectEls.length,
        }));
    }

    handleToC(translateEl) {
        if (translateEl.closest(".s_table_of_content_navbar_wrap")) {
            const href = translateEl.closest("a").getAttribute("href");
            const headerEl = translateEl
                .closest(".s_table_of_content")
                .querySelector(`${href} [data-oe-translation-source-sha]`);
            if (headerEl) {
                if (
                    translateEl.dataset.oeTranslationSourceSha !==
                    headerEl.dataset.oeTranslationSourceSha
                ) {
                    log.logic("handleToC: header sha differs, keep save sha", () => ({
                        href,
                    }));
                    translateEl.dataset.oeTranslationSaveSha =
                        translateEl.dataset.oeTranslationSourceSha;
                    translateEl.dataset.oeTranslationSourceSha =
                        headerEl.dataset.oeTranslationSourceSha;
                }
                translateEl.classList.add("o_translation_without_style");
            }
        }
    }

    markTranslatableNodes() {
        for (const [translateEl, translationInfo] of this.elToTranslationInfoMap) {
            for (const translationData of Object.values(translationInfo)) {
                if (translateEl.dataset.oeTranslationState !== "translated") {
                    translateEl.setAttribute(
                        "data-oe-translation-state",
                        translationData.oeTranslationState || "to_translate",
                    );
                }
            }
            this.addDomListener(translateEl, "click", (ev) => {
                const translateEl = ev.target;
                const elToTranslationInfoMap = this.elToTranslationInfoMap;
                log.lifecycle("AttributeTranslateDialog open", () => ({
                    tagName: translateEl.tagName,
                }));
                this.dialogService.add(AttributeTranslateDialog, {
                    node: translateEl,
                    elToTranslationInfoMap: elToTranslationInfoMap,
                    addStep: this.dependencies.history.addStep,
                    applyCustomMutation: this.dependencies.history.applyCustomMutation,
                });
            });
        }
        for (const translateSelectEl of this.translateSelectEls) {
            this.addDomListener(translateSelectEl, "click", (ev) => {
                const translateSelectEl = ev.target;
                log.lifecycle("SelectTranslateDialog open");
                this.dialogService.add(SelectTranslateDialog, {
                    node: translateSelectEl,
                    addStep: this.dependencies.history.addStep,
                });
            });
        }
        log.pipeline("dispatch mark_translatable_nodes", () => ({
            translated: this.elToTranslationInfoMap.size,
            selectOptions: this.translateSelectEls.length,
            editables: this.editableEls.length,
        }));
        this.dispatchTo("mark_translatable_nodes", this.editableEls);
    }

    updateTranslationMap(translateEl, translation, attrName) {
        const parser = new DOMParser();
        const dummyDoc = parser.parseFromString(translation, "text/html");
        const translationEl = dummyDoc.querySelector(
            "[data-oe-translation-source-sha]",
        );
        if (!translationEl) {
            log.logic("updateTranslationMap: no translation span", { attrName });
            return;
        }
        if (!this.elToTranslationInfoMap.get(translateEl)) {
            this.elToTranslationInfoMap.set(translateEl, {});
        }
        this.elToTranslationInfoMap.get(translateEl)[attrName] = translationEl.dataset;
        this.elToTranslationInfoMap.get(translateEl)[attrName].translation =
            translationEl.innerHTML;
    }

    /**
     * @returns {HTMLElement[]}
     */
    getDirtyTranslations() {
        const dirtyEls = [];
        for (const [translateEl, translationInfo] of this.elToTranslationInfoMap) {
            for (const [attr, data] of Object.entries(translationInfo)) {
                if (
                    this.originalElToTranslationInfoMap.get(translateEl)?.[attr]
                        ?.translation !== data.translation
                ) {
                    const spanEl = document.createElement("span");
                    for (const [name, value] of Object.entries(data)) {
                        spanEl.dataset[name] = value;
                    }
                    const translation = spanEl.dataset.translation;
                    delete spanEl.dataset.translation;
                    spanEl.innerHTML = translation;
                    dirtyEls.push(spanEl);
                }
            }
        }
        log.pipeline("getDirtyTranslations", () => ({
            tracked: this.elToTranslationInfoMap.size,
            dirty: dirtyEls.length,
        }));
        return dirtyEls;
    }

    cleanForSave({ root }) {
        root.querySelectorAll(".o_editable_attribute").forEach((el) => {
            el.classList.remove("o_editable_attribute");
        });
        const optionsEl = root.querySelector(".o_translation_select");
        if (optionsEl) {
            const selectEl = optionsEl.nextElementSibling;
            const translatedOptions = optionsEl.children;
            const selectOptions =
                selectEl.tagName === "SELECT" ? [...selectEl.options] : [];
            log.logic("cleanForSave: restore translated select options", () => ({
                selectOptions: selectOptions.length,
                translatedOptions: translatedOptions.length,
            }));
            if (selectOptions.length === translatedOptions.length) {
                selectOptions.map((option, i) => {
                    option.text = translatedOptions[i].textContent;
                });
            }
            optionsEl.remove();
        }
        if (root.dataset.oeTranslationSaveSha) {
            log.logic("cleanForSave: restore source sha from save sha");
            root.dataset.oeTranslationSourceSha = root.dataset.oeTranslationSaveSha;
            delete root.dataset.oeTranslationSaveSha;
        }
    }
}
