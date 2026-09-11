/** @odoo-module native */
import { BuilderAction } from "@html_builder/core/builder_action";
import { Plugin } from "@html_editor/plugin";
import { withSequence } from "@html_editor/utils/resource";
import { reactive } from "@odoo/owl";
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { uniqueId } from "@web/core/utils/functions";

import { TranslateWebpageOption } from "./translate_webpage_option.js";

/**
 * @typedef { Object } CustomizeTranslationTabShared
 * @property { CustomizeTranslationTabPlugin['getTranslationState'] } getTranslationState
 */

class TranslateToAction extends BuilderAction {
    static id = "translateWebpageAI";
    static dependencies = ["customizeTranslationTab"];

    async apply() {
        const translationState =
            this.dependencies.customizeTranslationTab.getTranslationState();
        try {
            translationState.isTranslating = true;
            const language = this.services.website.currentWebsite.metadata.langName;
            const { translationChunks, translationMap } =
                this.generateTranslationChunks(this.editable);
            if (translationChunks) {
                const responses = await this.runTranslationChunks(
                    translationChunks,
                    language,
                );
                const failedNodeCount = this.applyTranslationsToDOM(
                    translationMap,
                    responses,
                );
                if (failedNodeCount > 0) {
                    this.showNotification(
                        _t(
                            "%s text blocks were skipped during translation. Please try again.",
                            failedNodeCount,
                        ),
                        _t("Translation Error"),
                        "danger",
                    );
                }
            }
        } finally {
            translationState.isTranslating = false;
        }
    }

    /**
     * @param {Node} el
     * @return {boolean}
     */
    shouldSkipTranslation(el) {
        const text = el.textContent.replace(/[\u200B-\u200D\uFEFF]/g, "").trim();
        const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        const PHONE_REGEX = /^[+\d][\d\s\-().]{6,}$/;
        const URL_REGEX =
            /^(https?:\/\/)?([\w-]+\.)+[\w-]+(:\d+)?(\/[\w\-./?%&=]*)?(#\S*)?$/i;
        const LETTER_OR_NUMBER_REGEX = /\p{L}|\p{N}/u;
        return (
            !LETTER_OR_NUMBER_REGEX.test(text) ||
            EMAIL_REGEX.test(text) ||
            PHONE_REGEX.test(text) ||
            URL_REGEX.test(text)
        );
    }

    /**
     * @param {HTMLElement} containerEl
     * @param {number} limit
     * @return {Object}
     */
    generateTranslationChunks(containerEl, limit = 2000) {
        const elements = Array.from(
            containerEl.querySelectorAll("[data-oe-translation-state='to_translate']"),
        ).filter(
            (el) =>
                !el.closest(".o_not_editable, .o_frontend_to_backend_buttons") &&
                !el.classList.contains("o_translatable_attribute"),
        );

        const translationChunks = [];
        const translationMap = new Map();
        let currentChunk = [];
        let currentChunkLength = 0;
        const flushChunk = () => {
            if (currentChunk.length) {
                translationChunks.push(currentChunk);
                currentChunk = [];
                currentChunkLength = 0;
            }
        };

        for (const el of elements) {
            const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
            while (walker.nextNode()) {
                const nodeId = uniqueId("t_");
                const node = walker.currentNode;
                if (this.shouldSkipTranslation(node)) {
                    continue;
                }
                const text = node.textContent.trim();
                const itemSize = JSON.stringify({ id: nodeId, text }).length;
                if (currentChunkLength + itemSize > limit && currentChunk.length) {
                    flushChunk();
                }
                currentChunk.push({ el: node, id: nodeId, originalText: text });
                translationMap.set(nodeId, node);
                currentChunkLength += itemSize;
            }
        }
        flushChunk();

        if (!translationMap.size) {
            this.showNotification(
                _t("No translatable content found in the current webpage."),
                _t("Translation Info"),
                "info",
            );
            return {};
        }
        return { translationChunks, translationMap };
    }

    /**
     * @param {Array} translationChunks
     * @param {string} language
     * @return {Promise<Array>}
     */
    async runTranslationChunks(translationChunks, language) {
        const systemMessage = {
            role: "system",
            content:
                "You are a translation assistant. Your goal is to translate multiple text blocks.\n" +
                "Instructions:\n" +
                "- Input will be an array of objects: [{id: string, text: string}, ...]\n" +
                "- Return ONLY valid JSON in the same array format, replacing 'text' with the translated text.\n" +
                "- Do not add comments or extra fields.",
        };

        const tasks = translationChunks.map((chunk) => async () => {
            const prompt = JSON.stringify(
                chunk.map(({ id, originalText }) => ({ id, text: originalText })),
            );
            const conversation = [
                systemMessage,
                {
                    role: "user",
                    content: `Translate the following to ${language}:\n\n${prompt}`,
                },
            ];
            return rpc(
                "/html_editor/generate_text",
                {
                    prompt: prompt,
                    conversation_history: conversation,
                },
                { silent: true },
            );
        });

        const concurrencyLimit = 5;
        const allResults = [];
        const executing = new Set();
        for (const task of tasks) {
            if (executing.size >= concurrencyLimit) {
                await Promise.race(executing);
            }
            const promise = task()
                .catch(() => null)
                .finally(() => executing.delete(promise));
            executing.add(promise);
            allResults.push(promise);
        }
        return Promise.all(allResults);
    }

    /**
     * @param {Map<string, Object} translationMap
     * @param {Array} responses
     * @return {Number}
     */
    applyTranslationsToDOM(translationMap, responses) {
        let numOfFailedTranslationNodes = 0;
        for (const response of responses) {
            if (response == null) {
                continue;
            }
            let translations;
            try {
                translations = JSON.parse(response);
            } catch {
                numOfFailedTranslationNodes += translationMap.size;
                continue;
            }

            for (const { id, text } of translations) {
                const node = translationMap.get(id);
                if (!node) {
                    continue;
                }
                const translated = (text || "").trim();
                if (!translated) {
                    numOfFailedTranslationNodes++;
                    continue;
                }
                node.textContent = translated;
                const parentEl = node.parentElement?.closest(
                    "[data-oe-translation-state]",
                );
                if (parentEl) {
                    parentEl.dataset.oeTranslationState = "translated";
                }
            }
        }
        return numOfFailedTranslationNodes;
    }

    showNotification(message, title, type) {
        this.services.notification.add(message, {
            title: title,
            type,
            sticky: true,
        });
    }
}

export class CustomizeTranslationTabPlugin extends Plugin {
    static id = "customizeTranslationTab";
    static shared = ["getTranslationState"];

    translationState = reactive({
        isTranslating: false,
    });

    /** @type {import("plugins").WebsiteResources} */
    resources = {
        builder_actions: {
            TranslateToAction,
        },
        translate_options: [
            withSequence(
                1,
                this.getTranslationOptionBlock(
                    "translate-webpage",
                    _t("Translation"),
                    TranslateWebpageOption,
                ),
            ),
        ],
    };

    getTranslationState() {
        return this.translationState;
    }

    /**
     * @param {string} id
     * @param {string} name
     * @param {Object} Option
     */
    getTranslationOptionBlock(id, name, Option) {
        const el = this.document.createElement("div");
        el.dataset.name = name;
        this.document.body.appendChild(el);
        this._cleanups.push(() => el.remove());

        return {
            id: id,
            snippetModel: {},
            element: el,
            options: [Option],
            isRemovable: false,
            isClonable: false,
            containerTopButtons: [],
        };
    }
}

registry
    .category("translation-plugins")
    .add(CustomizeTranslationTabPlugin.id, CustomizeTranslationTabPlugin);
