// @ts-check
/** @odoo-module native */

import { browser } from "@web/core/browser/browser";
import { session } from "@web/session";

/** @typedef {boolean | number | string | null} FeatureFlagValue */

/**
 * @typedef {{
 * default?: FeatureFlagValue;
 * description?: string;
 * }} FeatureFlagOptions
 */

const LS_PREFIX = "feature.";
const URL_PARAM_NAME = "features";

/**
 * @param {string} raw
 * @returns {FeatureFlagValue}
 */
function _parseValue(raw) {
    const trimmed = raw.trim();
    if (trimmed === "true") {
        return true;
    }
    if (trimmed === "false") {
        return false;
    }
    if (trimmed === "null") {
        return null;
    }
    if (trimmed === "") {
        return true;
    }
    const n = Number(trimmed);
    if (Number.isFinite(n) && /^-?(\d+\.?\d*|\.\d+)$/.test(trimmed)) {
        return n;
    }
    if (trimmed.length >= 2 && trimmed.startsWith(`"`) && trimmed.endsWith(`"`)) {
        try {
            const unquoted = JSON.parse(trimmed);
            if (typeof unquoted === "string") {
                return unquoted;
            }
        } catch {}
    }
    return trimmed;
}

/**
 * @param {FeatureFlagValue} value
 * @returns {string}
 */
function _serializeValue(value) {
    if (typeof value !== "string") {
        return String(value);
    }
    if (value !== value.trim() || _parseValue(value) !== value) {
        return JSON.stringify(value);
    }
    return value;
}

/**
 * @type {Map<string, FeatureFlagValue> | null}
 */
let _urlOverrides = null;

/**
 * @param {string} raw
 * @returns {Map<string, FeatureFlagValue>}
 */
function _parseUrlFeatures(raw) {
    const out = new Map();
    for (const part of raw.split(/[,;]/)) {
        const token = part.trim();
        if (!token) {
            continue;
        }
        const colonIdx = token.indexOf(":");
        if (colonIdx !== -1) {
            const name = token.slice(0, colonIdx).trim();
            const value = _parseValue(token.slice(colonIdx + 1));
            if (name) {
                out.set(name, value);
            }
        } else if (token.startsWith("-")) {
            out.set(token.slice(1).trim(), false);
        } else {
            out.set(token, true);
        }
    }
    return out;
}

/**
 * @returns {Map<string, FeatureFlagValue>}
 */
function _getUrlOverrides() {
    if (_urlOverrides !== null) {
        return _urlOverrides;
    }
    _urlOverrides = new Map();
    try {
        const href = browser.location?.href;
        if (href) {
            const raw = new URL(href).searchParams.get(URL_PARAM_NAME);
            if (raw) {
                _urlOverrides = _parseUrlFeatures(raw);
            }
        }
    } catch {}
    return _urlOverrides;
}

/**
 * @type {Map<string, FeatureFlagValue | undefined>}
 */
const _fromSources = new Map();

/**
 * @param {string} name
 * @returns {FeatureFlagValue | undefined}
 */
function _readLocalStorage(name) {
    try {
        const raw = browser.localStorage?.getItem(LS_PREFIX + name);
        if (raw === null || raw === undefined) {
            return undefined;
        }
        return _parseValue(raw);
    } catch {
        return undefined;
    }
}

/**
 * @param {string} name
 * @returns {FeatureFlagValue | undefined}
 */
function _readServer(name) {
    const flags = session?.feature_flags;
    if (flags && Object.hasOwn(flags, name)) {
        return flags[name];
    }
    return undefined;
}

/**
 * @param {string} name
 * @param {FeatureFlagOptions} [options]
 * @returns {FeatureFlagValue}
 */
export function featureFlag(name, options = {}) {
    const fromSources = _readSources(name);
    if (fromSources !== undefined) {
        return fromSources;
    }
    return options.default === undefined ? false : options.default;
}

/**
 * @param {string} name
 * @returns {FeatureFlagValue | undefined}
 */
function _readSources(name) {
    if (_fromSources.has(name)) {
        return _fromSources.get(name);
    }
    const urlOverrides = _getUrlOverrides();
    let value;
    if (urlOverrides.has(name)) {
        value = urlOverrides.get(name);
    } else {
        const fromLs = _readLocalStorage(name);
        value = fromLs !== undefined ? fromLs : _readServer(name);
    }
    _fromSources.set(name, value);
    return value;
}

/**
 * @param {string} name
 * @param {FeatureFlagValue} value
 */
export function setFeatureFlag(name, value) {
    _fromSources.delete(name);
    try {
        browser.localStorage?.setItem(LS_PREFIX + name, _serializeValue(value));
    } catch {}
}

/**
 * @param {string} name
 */
export function clearFeatureFlag(name) {
    _fromSources.delete(name);
    try {
        browser.localStorage?.removeItem(LS_PREFIX + name);
    } catch {}
}

export function _resetFeatureFlagsCache() {
    _urlOverrides = null;
    _fromSources.clear();
}

/**
 * @returns {Array<{ name: string; value: FeatureFlagValue; source: "url" | "localStorage" | "server"; }>}
 */
export function getFeatureFlagsSnapshot() {
    /**
     * @type {{ name: string; value: FeatureFlagValue; source: "url" | "server" | "localStorage" }[]}
     */
    const out = [];
    const seen = new Set();
    const urlOverrides = _getUrlOverrides();
    for (const [name, value] of urlOverrides) {
        out.push({ name, value, source: "url" });
        seen.add(name);
    }
    try {
        const ls = browser.localStorage;
        if (ls) {
            for (let i = 0; i < ls.length; i++) {
                const key = ls.key(i);
                if (key && key.startsWith(LS_PREFIX)) {
                    const name = key.slice(LS_PREFIX.length);
                    if (!seen.has(name)) {
                        out.push({
                            name,
                            value: _parseValue(ls.getItem(key) || ""),
                            source: "localStorage",
                        });
                        seen.add(name);
                    }
                }
            }
        }
    } catch {}
    const serverFlags = session?.feature_flags;
    if (serverFlags) {
        for (const [name, value] of Object.entries(serverFlags)) {
            if (!seen.has(name)) {
                out.push({ name, value, source: "server" });
                seen.add(name);
            }
        }
    }
    return out;
}
