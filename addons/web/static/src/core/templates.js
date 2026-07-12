// @ts-check
/** @odoo-module native */

/** @module @web/core/templates - Template registry: parses, inherits, caches, and retrieves QWeb templates */

import {
    applyContextToTextNode,
    applyInheritance,
    deepClone,
} from "@web/core/template_inheritance";
import { makeAssetLog } from "@web/core/utils/asset_log";

const log = makeAssetLog("templates");

/**
 * @param {Element} template
 * @returns {Element}
 */
function getClone(template) {
    const c = /** @type {Element} */ (deepClone(template));
    new Document().append(c); // => c is the documentElement of its ownerDocument
    return c;
}

/**
 * cyrb53 — a fast, well-distributed 53-bit string hash (public domain,
 * https://github.com/bryc/code). Used instead of the 32-bit
 * ``hashCode`` from ``@web/core/utils/format/strings`` because the
 * ``registered`` dedup set can hold tens of thousands of entries, where
 * 32-bit birthday collisions become likely — and a collision here would
 * silently skip registering a template.
 *
 * @param {string} str
 * @returns {number}
 */
function cyrb53(str) {
    let h1 = 0xdeadbeef;
    let h2 = 0x41c6ce57;
    for (let i = 0; i < str.length; i++) {
        const ch = str.charCodeAt(i);
        h1 = Math.imul(h1 ^ ch, 2654435761);
        h2 = Math.imul(h2 ^ ch, 1597334677);
    }
    h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507);
    h1 ^= Math.imul(h2 ^ (h2 >>> 13), 3266489909);
    h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507);
    h2 ^= Math.imul(h1 ^ (h1 >>> 13), 3266489909);
    return 4294967296 * (2097151 & h2) + (h1 >>> 0);
}

/**
 * Dedup key for a ``[name, url, templateString]`` registration triple.
 * Hashed so the ``registered`` set doesn't retain a full copy of every
 * template string (several MB over a session) for its whole lifetime.
 *
 * @param {unknown[]} args
 */
function getKey(args) {
    return String(cyrb53(JSON.stringify(args)));
}

/**
 * Scoped registry for QWeb templates, their inheritance extensions, and
 * the processor pipeline that transforms parsed XML before it is cached.
 * Replaces 12 module-level mutable bindings with instance state.
 *
 * Anchored on ``globalThis`` (like ``core/registry.js``) so the esbuild
 * bundles this module gets inlined into (``web.assets_web``,
 * ``web.assets_unit_tests``, dynamic children) share one instance instead
 * of splitting template registrations across copies.
 *
 * The historical module-level functions below delegate to the canonical
 * singleton so the ~28 existing import sites don't need to change.
 */
export class TemplateRegistry {
    constructor() {
        this._parser = new DOMParser();
        /** @type {Record<string, string>} */
        this.templates = Object.create(null);
        this.info = Object.create(null);
        // Only ever holds `_parse(...)` results, which are non-null Elements.
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
        /** @type {Set<string>} Recursion guard for circular t-inherit chains. */
        this._inheritanceChain = new Set();
    }

    /**
     * Parse a raw template string and run the registered processor
     * pipeline. Returns the root element ready for inheritance / extension
     * processing.
     *
     * @param {string} templateString
     * @returns {Element}
     */
    _parse(templateString) {
        const doc = this._parser.parseFromString(templateString, "text/xml");
        const parseError = doc.querySelector("parsererror");
        if (parseError) {
            // A malformed template was previously compiled as-is (the
            // <parsererror> doc), or `firstChild` picked up a leading
            // comment/PI (a non-Element) and later blew up on `.getAttribute`.
            throw new Error(`Invalid template:\n${parseError.textContent}`);
        }
        for (const processor of this.templateProcessors) {
            processor(doc);
        }
        // documentElement is the root Element, robust to leading comments /
        // processing instructions that would make firstChild a non-Element.
        return doc.documentElement;
    }

    /**
     * Internal recursive resolver: parses ``name`` (cached), applies its
     * ``t-inherit`` parent (if any), then layers all extension blocks
     * whose blockId predates ``blockId``.
     *
     * @param {string} name
     * @param {number | null} [blockId]
     */
    _getTemplate(name, blockId = null) {
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
        for (const otherBlockId of Object.keys(this.templateExtensions[name] || {})) {
            if (blockId && Number(otherBlockId) > blockId) {
                break;
            }
            if (!(name in this.parsedTemplateExtensions)) {
                this.parsedTemplateExtensions[name] = {};
            }
            if (!(otherBlockId in this.parsedTemplateExtensions[name])) {
                this.parsedTemplateExtensions[name][otherBlockId] = [];
                for (const { templateString, url } of this.templateExtensions[name][
                    Number(otherBlockId)
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
     * Fetch a compiled template by name, building it on first request and
     * caching the result.
     *
     * @param {string} name
     */
    getTemplate(name) {
        if (!this.processedTemplates.has(name)) {
            log("compile", name);
            this.processedTemplates.set(name, this._getTemplate(name));
            applyContextToTextNode();
        }
        return this.processedTemplates.get(name);
    }

    /**
     * Register a primary template.  Returns an unregister callback so test
     * harnesses can opt into per-test cleanup.
     *
     * @param {string} name
     * @param {string} url
     * @param {string} templateString
     */
    registerTemplate(name, url, templateString) {
        const key = getKey([name, url, templateString]);
        if (this.registered.has(key)) {
            // Verify the hit against the actual stored registration: the
            // dedup keys are 53-bit hashes, and treating a (however
            // unlikely) collision as a duplicate would silently skip
            // registering a template — an undiagnosable failure mode. A
            // mismatch falls through to a real registration attempt.
            if (
                this.templates[name] === templateString &&
                this.info[name]?.url === url
            ) {
                // True duplicate: return a callable no-op so
                // ``const un = registerTemplate(...); un()`` works
                // regardless of registration order in test lifecycles.
                // Unregistration stays owned by the FIRST registration's
                // callback.
                return () => {};
            }
        } else {
            this.registered.add(key);
        }
        log("register", name, "url=", url);
        if (this.blockType !== "templates") {
            this.blockType = "templates";
            this.blockId++;
        }
        if (
            name in this.templates &&
            (this.info[name].url !== url || this.templates[name] !== templateString)
        ) {
            throw new Error(`Template ${name} already exists`);
        }
        this.templates[name] = templateString;
        this.info[name] = { blockId: this.blockId, url };
        // Evict a stale negative-cache entry: a prior getTemplate(name) probe
        // before registration may have cached `null` permanently, which
        // would make a lazy bundle serve `null` forever after this call.
        this.processedTemplates.delete(name);

        return () => {
            delete this.templates[name];
            delete this.info[name];
            delete this.parsedTemplates[name];
            delete this.parsedTemplateExtensions[name];
            // Drop leftover blockId entries in templateExtensions too, or
            // they'd be iterated as orphans by _getTemplate if `name` is
            // re-registered later (e.g. between tests), leaking stale
            // parsed-extension state.
            delete this.templateExtensions[name];
            this.processedTemplates.delete(name);
            this.registered.delete(key);
        };
    }

    /**
     * Register a template extension (``t-inherit-mode="extension"``).
     * Returns an unregister callback.
     *
     * @param {string} inheritFrom
     * @param {string} url
     * @param {string} templateString
     */
    registerTemplateExtension(inheritFrom, url, templateString) {
        const key = getKey([inheritFrom, url, templateString]);
        if (this.registered.has(key)) {
            // Same hash-collision guard as ``registerTemplate``: only treat
            // the hit as a duplicate if this exact extension is registered.
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
            this.templateExtensions[inheritFrom] = [];
        }
        if (!this.templateExtensions[inheritFrom][this.blockId]) {
            this.templateExtensions[inheritFrom][this.blockId] = [];
        }
        const blockId = this.blockId;
        this.templateExtensions[inheritFrom][blockId].push({
            templateString,
            url,
        });
        // Evict any compiled/negative cache entry for the parent: a prior
        // getTemplate(inheritFrom) — from an eager render before a lazy bundle
        // registered this extension — would otherwise keep serving the
        // pre-extension DOM forever. Symmetric with registerTemplate and with
        // this method's own unregister callback below. (OWL Apps that already
        // compiled the template keep their closure — same caveat as there.)
        delete this.parsedTemplateExtensions[inheritFrom]?.[blockId];
        this.processedTemplates.delete(inheritFrom);

        return () => {
            const index = this.templateExtensions[inheritFrom]?.[blockId]?.findIndex(
                (ext) => ext.templateString === templateString && ext.url === url,
            );
            if (Number.isInteger(index) && index > -1) {
                this.templateExtensions[inheritFrom][blockId].splice(index, 1);
            }
            // Splicing the raw descriptor isn't enough: the parsed copy and
            // compiled result are cached separately, and a later
            // getTemplate(inheritFrom) would re-apply the removed extension
            // from that stale cache if left untouched.
            delete this.parsedTemplateExtensions[inheritFrom]?.[blockId];
            this.processedTemplates.delete(inheritFrom);
            this.registered.delete(key);
        };
    }

    /**
     * Append a processor function applied to every parsed template DOM.
     *
     * @param {(document: Document) => void} processor
     */
    registerTemplateProcessor(processor) {
        this.templateProcessors.push(processor);
    }

    /**
     * Check that the listed primary template parents have been registered.
     * Logs an error (without throwing) when any are missing.  Called from
     * generated bundle.xml code.
     *
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
     * Replace the URL-filter chain.  Returns a restore callback so tests
     * can scope a filter to a single suite.
     *
     * @param {((url: string) => boolean)[]} filters
     */
    setUrlFilters(filters) {
        const prev = this.urlFilters;
        this.urlFilters = filters;
        return () => {
            this.urlFilters = prev;
        };
    }

    /**
     * Drop the cache of compiled-template-on-first-access results.
     * Used by Hoot tests that need to re-process templates between
     * runs (e.g. after a processor mutation).
     */
    clearProcessedTemplates() {
        this.processedTemplates.clear();
    }
}

// ---------------------------------------------------------------------------
// Canonical shared instance + backward-compatible module-level functions
// ---------------------------------------------------------------------------

/**
 * Anchored on ``globalThis`` for the same bundle-sharing reason as the
 * class doc above. Bundle-evaluation order is deterministic: the first
 * bundle to load creates the instance, subsequent bundles rebind via
 * ``??=``.
 *
 * @type {TemplateRegistry}
 */
export const templates =
    /** @type {any} */ (globalThis).__odooTemplates__ ??
    /** @type {any} */ (globalThis.__odooTemplates__ = new TemplateRegistry());

// ---------------------------------------------------------------------------
// Backward-compatible module-level wrappers
//
// Pre-class API: 28 import sites across core+enterprise+agromarin call
// these named functions.  Keep them as thin delegates so no consumer
// has to change.  Each wrapper closes over ``templates`` (the shared
// singleton); the binding survives when functions are passed by
// reference (e.g. ``new App({ getTemplate })`` in env.js).
// ---------------------------------------------------------------------------

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

export function clearProcessedTemplates() {
    return templates.clearProcessedTemplates();
}
