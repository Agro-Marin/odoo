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
 *
 * Encapsulates the state that used to live as 12 module-level mutable
 * bindings (``templates``, ``info``, ``parsedTemplates``, ``processedTemplates``,
 * ``templateExtensions``, ``parsedTemplateExtensions``, ``registered``,
 * ``templateProcessors``, ``urlFilters``, plus the ``blockType`` / ``blockId``
 * cursors and the ``_inheritanceChain`` recursion guard).
 *
 * **Why a class.** The per-bundle registry (``core/registry.js``) is
 * already anchored on ``globalThis`` so sibling esbuild bundles share
 * one source of truth.  Templates need the same anchor for the same
 * reason — esbuild inlines this module into ``web.assets_web``,
 * ``web.assets_unit_tests``, and every manifest-declared
 * ``esm.dynamic_children`` child,
 * and a per-copy state map would split template registrations across
 * bundles.  Lifting the state onto an explicit class makes the anchor
 * explicit and unlocks scoped instances for embedded apps that want
 * their own template scope (a use case opened by ``.fork()`` —
 * see method below).
 *
 * **Backward compatibility.** The historical module-level functions
 * (``getTemplate``, ``registerTemplate``, ``registerTemplateExtension``,
 * ``registerTemplateProcessor``, ``checkPrimaryTemplateParents``,
 * ``setUrlFilters``, ``clearProcessedTemplates``) are kept as
 * thin wrappers that delegate to the canonical singleton below, so
 * the 28 import sites across the fork do not need to be touched.
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
        for (const processor of this.templateProcessors) {
            processor(doc);
        }
        return /** @type {Element} */ (doc.firstChild);
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
            return;
        }
        this.registered.add(key);
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
        // A prior ``getTemplate(name)`` probe before this registration would
        // have cached a ``null`` result (``_getTemplate`` returns null for an
        // unknown name, and ``getTemplate`` memoises it behind a ``has()``
        // guard).  That null is otherwise permanent: without this eviction a
        // lazy bundle that registers ``name`` after something probed for it
        // would serve ``null`` forever.  Drop the negative cache entry so the
        // freshly-registered template is (re)built on next access.
        this.processedTemplates.delete(name);

        return () => {
            delete this.templates[name];
            delete this.info[name];
            delete this.parsedTemplates[name];
            delete this.parsedTemplateExtensions[name];
            // Drop the raw extensions registry slot.  ``templateExtensions``
            // keeps a per-blockId array of extension descriptors keyed by
            // the primary template name; once that primary is gone, any
            // leftover (possibly already-spliced-to-empty) blockId entries
            // are orphans that would still be iterated by ``_getTemplate``
            // if the same ``name`` is later re-registered (e.g. between
            // tests), causing stale, never-rebuilt parsed-extension state
            // to leak.
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
            return;
        }
        this.registered.add(key);
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

        return () => {
            const index = this.templateExtensions[inheritFrom]?.[blockId]?.findIndex(
                (ext) => ext.templateString === templateString && ext.url === url,
            );
            if (Number.isInteger(index) && index > -1) {
                this.templateExtensions[inheritFrom][blockId].splice(index, 1);
            }
            // Splicing the raw descriptor is not enough: the *parsed* copy of
            // this block lives in ``parsedTemplateExtensions[inheritFrom][blockId]``
            // and the compiled result in ``processedTemplates[inheritFrom]``.
            // Left untouched, a later ``getTemplate(inheritFrom)`` re-applies
            // the just-removed extension from that stale parse cache.  Mirror
            // the primary-template unregister invalidation and drop both.
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
 * Anchor the canonical TemplateRegistry on ``globalThis`` for the same
 * reason ``core/registry.js`` does — esbuild inlines this module into
 * multiple bundles (``web.assets_web``, ``web.assets_unit_tests``, each
 * manifest-declared ``esm.dynamic_children`` child), and a per-copy
 * state map would split
 * template registrations across bundles.  Bundle-evaluation order is
 * deterministic; the first bundle to load creates the instance, all
 * subsequent bundles re-bind ``templates`` to the same object via
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
