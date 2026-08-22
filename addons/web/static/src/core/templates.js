// @ts-check
/** @odoo-module native */

import {
    applyContextToTextNode,
    applyInheritance,
    deepClone,
    discardPendingTranslationContexts,
} from "@web/core/template_inheritance";
import { makeAssetLog } from "@web/core/utils/asset_log";
import { cyrb53 } from "@web/core/utils/format/strings";
import { globalSingleton } from "@web/core/utils/global_singleton";

const log = makeAssetLog("templates");

/**
 * @param {Element} template
 * @returns {Element}
 */
function getClone(template) {
    const c = /** @type {Element} */ (deepClone(template));
    new Document().append(c);
    return c;
}

/**
 * @param {[string, string, string]} args
 * @returns {string}
 */
function getKey([name, url, templateString]) {
    return JSON.stringify([name, url, cyrb53(templateString)]);
}

export class TemplateRegistry {
    constructor() {
        this._parser = new DOMParser();
        /** @type {Record<string, string>} */
        this.templates = Object.create(null);
        this.info = Object.create(null);
        /** @type {Record<string, Element>} */
        this.parsedTemplates = Object.create(null);
        this.parsedTemplateExtensions = Object.create(null);
        /** @type {Map<string, Element | null>} */
        this.processedTemplates = new Map();
        /** @type {Set<string>} */
        this.registered = new Set();
        /** @type {Record<string, Record<number, ({ templateString: string, url: string })[]>>} */
        this.templateExtensions = Object.create(null);
        /** @type {((document: Document) => void)[]} */
        this.templateProcessors = [];
        /** @type {((url: string) => boolean)[]} */
        this.urlFilters = [];
        /** @type {string | null} */
        this.blockType = null;
        this.blockId = 0;
        /** @type {Set<string>} */
        this._inheritanceChain = new Set();
        /**
         * @type {Map<string, Set<string>>}
         */
        this._dependents = new Map();
        /**
         * @type {Set<string> | null}
         */
        this._currentSources = null;
    }

    /**
     * @param {string} name
     */
    _recordSource(name) {
        this._currentSources?.add(name);
    }

    /**
     * @param {string} name
     */
    _invalidateProcessed(name) {
        const stale = [name];
        const seen = new Set(stale);
        while (stale.length) {
            const current = /** @type {string} */ (stale.pop());
            this.processedTemplates.delete(current);
            for (const dependent of this._dependents.get(current) || []) {
                if (!seen.has(dependent)) {
                    seen.add(dependent);
                    stale.push(dependent);
                }
            }
            this._dependents.delete(current);
        }
    }

    /**
     * @param {string} templateString
     * @returns {Element}
     */
    _parse(templateString) {
        const doc = this._parser.parseFromString(templateString, "text/xml");
        const parseError = doc.querySelector("parsererror");
        if (parseError) {
            throw new Error(`Invalid template:\n${parseError.textContent}`);
        }
        for (const processor of this.templateProcessors) {
            processor(doc);
        }
        return doc.documentElement;
    }

    /**
     * @param {string} name
     * @param {number | null} [blockId]
     */
    _getTemplate(name, blockId = null) {
        this._recordSource(name);
        if (!(name in this.parsedTemplates)) {
            if (!(name in this.templates)) {
                return null;
            }
            const templateString = this.templates[name];
            this.parsedTemplates[name] = this._parse(templateString);
            const inheritFrom = this.parsedTemplates[name].getAttribute("t-inherit");
            if (!inheritFrom) {
                const addon = this.info[name].url.split("/")[1];
                this.parsedTemplates[name].setAttribute("t-translation-context", addon);
            }
        }
        let processedTemplate = this.parsedTemplates[name];

        const inheritFrom = processedTemplate.getAttribute("t-inherit");
        if (inheritFrom) {
            if (this._inheritanceChain.has(name)) {
                throw new Error(
                    `Circular template inheritance detected: ${[...this._inheritanceChain, name].join(" → ")}`,
                );
            }
            this._inheritanceChain.add(name);
            let parentTemplate;
            try {
                parentTemplate = this._getTemplate(
                    inheritFrom,
                    blockId || this.info[name].blockId,
                );
            } finally {
                this._inheritanceChain.delete(name);
            }
            if (!parentTemplate) {
                throw new Error(
                    `Constructing template ${name}: template parent ${inheritFrom} not found`,
                );
            }
            const element = getClone(processedTemplate);
            processedTemplate = applyInheritance(
                getClone(parentTemplate),
                element,
                this.info[name].url,
            );
            if (processedTemplate.tagName !== element.tagName) {
                const temp = processedTemplate;
                processedTemplate = new Document().createElement(element.tagName);
                processedTemplate.append(...temp.childNodes);
            }
            for (const { name: attrName, value } of element.attributes) {
                if (!["t-inherit", "t-inherit-mode"].includes(attrName)) {
                    processedTemplate.setAttribute(attrName, value);
                }
            }
        }

        let cloned = false;
        const blockIds = Object.keys(this.templateExtensions[name] || {})
            .map(Number)
            .sort((a, b) => a - b);
        for (const otherBlockId of blockIds) {
            if (blockId && otherBlockId > blockId) {
                break;
            }
            if (!(name in this.parsedTemplateExtensions)) {
                this.parsedTemplateExtensions[name] = {};
            }
            if (!(otherBlockId in this.parsedTemplateExtensions[name])) {
                this.parsedTemplateExtensions[name][otherBlockId] = [];
                for (const { templateString, url } of this.templateExtensions[name][
                    otherBlockId
                ]) {
                    this.parsedTemplateExtensions[name][otherBlockId].push({
                        template: this._parse(templateString),
                        url,
                    });
                }
            }
            for (const { template, url } of this.parsedTemplateExtensions[name][
                otherBlockId
            ]) {
                if (!this.urlFilters.every((filter) => filter(url))) {
                    continue;
                }
                if (!inheritFrom && !cloned) {
                    cloned = true;
                    processedTemplate = getClone(processedTemplate);
                }
                processedTemplate = applyInheritance(
                    processedTemplate,
                    getClone(template),
                    url,
                );
            }
        }

        return processedTemplate;
    }

    /**
     * @param {string} name
     */
    getTemplate(name) {
        if (!this.processedTemplates.has(name)) {
            log("compile", name);
            const outerSources = this._currentSources;
            const sources = new Set();
            this._currentSources = sources;
            try {
                this.processedTemplates.set(name, this._getTemplate(name));
                for (const source of sources) {
                    if (source === name) {
                        continue;
                    }
                    let dependents = this._dependents.get(source);
                    if (!dependents) {
                        dependents = new Set();
                        this._dependents.set(source, dependents);
                    }
                    dependents.add(name);
                }
                applyContextToTextNode();
            } finally {
                this._currentSources = outerSources;
                discardPendingTranslationContexts();
            }
        }
        return this.processedTemplates.get(name);
    }

    /**
     * @param {string} name
     * @param {string} url
     * @param {string} templateString
     */
    registerTemplate(name, url, templateString) {
        const key = getKey([name, url, templateString]);
        if (
            this.registered.has(key) &&
            this.templates[name] === templateString &&
            this.info[name]?.url === url
        ) {
            return () => {};
        }
        if (
            name in this.templates &&
            (this.info[name].url !== url || this.templates[name] !== templateString)
        ) {
            throw new Error(`Template ${name} already exists`);
        }
        this.registered.add(key);
        log("register", name, "url=", url);
        if (this.blockType !== "templates") {
            this.blockType = "templates";
            this.blockId++;
        }
        this.templates[name] = templateString;
        this.info[name] = { blockId: this.blockId, url };
        this._invalidateProcessed(name);

        return () => {
            delete this.templates[name];
            delete this.info[name];
            delete this.parsedTemplates[name];
            delete this.parsedTemplateExtensions[name];
            this._invalidateProcessed(name);
            this.registered.delete(key);
        };
    }

    /**
     * @param {string} inheritFrom
     * @param {string} url
     * @param {string} templateString
     */
    registerTemplateExtension(inheritFrom, url, templateString) {
        const key = getKey([inheritFrom, url, templateString]);
        if (this.registered.has(key)) {
            const isRegistered = Object.values(
                this.templateExtensions[inheritFrom] || {},
            ).some((block) =>
                block.some(
                    (ext) => ext.templateString === templateString && ext.url === url,
                ),
            );
            if (isRegistered) {
                return () => {};
            }
        } else {
            this.registered.add(key);
        }
        if (this.blockType !== "extensions") {
            this.blockType = "extensions";
            this.blockId++;
        }
        if (!this.templateExtensions[inheritFrom]) {
            this.templateExtensions[inheritFrom] = {};
        }
        if (!this.templateExtensions[inheritFrom][this.blockId]) {
            this.templateExtensions[inheritFrom][this.blockId] = [];
        }
        const blockId = this.blockId;
        this.templateExtensions[inheritFrom][blockId].push({
            templateString,
            url,
        });
        delete this.parsedTemplateExtensions[inheritFrom]?.[blockId];
        this._invalidateProcessed(inheritFrom);

        return () => {
            const index = this.templateExtensions[inheritFrom]?.[blockId]?.findIndex(
                (ext) => ext.templateString === templateString && ext.url === url,
            );
            if (Number.isInteger(index) && index > -1) {
                this.templateExtensions[inheritFrom][blockId].splice(index, 1);
            }
            delete this.parsedTemplateExtensions[inheritFrom]?.[blockId];
            this._invalidateProcessed(inheritFrom);
            this.registered.delete(key);
        };
    }

    _invalidateAllDerived() {
        this.parsedTemplates = Object.create(null);
        this.parsedTemplateExtensions = Object.create(null);
        this.processedTemplates.clear();
        this._dependents.clear();
    }

    /**
     * @param {(document: Document) => void} processor
     */
    registerTemplateProcessor(processor) {
        this.templateProcessors.push(processor);
        this._invalidateAllDerived();
    }

    /**
     * @param {string[]} namesToCheck
     */
    checkPrimaryTemplateParents(namesToCheck) {
        const missing = new Set(
            namesToCheck.filter((name) => !(name in this.templates)),
        );
        if (missing.size) {
            console.error(
                `Missing (primary) parent templates: ${[...missing].join(", ")}`,
            );
        }
    }

    /**
     * @param {((url: string) => boolean)[]} filters
     */
    setUrlFilters(filters) {
        const prev = this.urlFilters;
        this.urlFilters = filters;
        this.processedTemplates.clear();
        this._dependents.clear();
        return () => {
            this.urlFilters = prev;
            this.processedTemplates.clear();
            this._dependents.clear();
        };
    }
}

/**
 * @type {TemplateRegistry}
 */
export const templates = globalSingleton("templates", () => new TemplateRegistry());

/**
 * @param {string} name
 */
export function getTemplate(name) {
    return templates.getTemplate(name);
}

/**
 * @param {string} name
 * @param {string} url
 * @param {string} templateString
 */
export function registerTemplate(name, url, templateString) {
    return templates.registerTemplate(name, url, templateString);
}

/**
 * @param {string} inheritFrom
 * @param {string} url
 * @param {string} templateString
 */
export function registerTemplateExtension(inheritFrom, url, templateString) {
    return templates.registerTemplateExtension(inheritFrom, url, templateString);
}

/**
 * @param {(document: Document) => void} processor
 */
export function registerTemplateProcessor(processor) {
    return templates.registerTemplateProcessor(processor);
}

/**
 * @param {string[]} namesToCheck
 */
export function checkPrimaryTemplateParents(namesToCheck) {
    return templates.checkPrimaryTemplateParents(namesToCheck);
}

/**
 * @param {((url: string) => boolean)[]} filters
 */
export function setUrlFilters(filters) {
    return templates.setUrlFilters(filters);
}
