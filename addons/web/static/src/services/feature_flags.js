// @ts-check
/** @odoo-module native */

/** @module @web/services/feature_flags - Centralized feature-flag resolution (URL > localStorage > server > default) */

import { browser } from "@web/core/browser/browser";
import { session } from "@web/session";

/**
 *   import { featureFlag } from "@web/services/feature_flags";
 *
 *   if (featureFlag("perf_marks", { default: false })) {
 *       performance.mark("…");
 *   }
 *
 * Resolution cascade — first source that has the flag wins:
 *   1. URL ``?features=name,-name,name:value`` (comma/semicolon
 *      separated; value parsed as JSON-ish: true/false/null/number/
 *      string). Highest priority — for one-off A/B testing or
 *      reproducing a report.
 *   2. ``localStorage["feature.<name>"]`` — per-device override,
 *      parsed the same way, survives reload.
 *   3. ``session.feature_flags[<name>]`` — server-emitted default from
 *      ``ir.config_parameter`` (``web.feature.`` prefix, see
 *      ``models/ir_http.py``). Deployment-wide rollout knob.
 *   4. ``options.default`` (``false`` if omitted).
 *
 * Pure function, no service: flags are read on hot paths (boot,
 * per-render, per-RPC) where routing through ``useService`` would force
 * every call site into a component. URL and localStorage are read
 * eagerly and cached for the session (O(1) lookups thereafter); the
 * server dict is captured at module load and never refetched — reload
 * is the upgrade path. Flag names are free-form (``snake_case``
 * convention, no ``.``/``:``/``,`` — reserved for the URL parser). The
 * cache is keyed by ``name`` alone — encode any sub-dimension into the
 * name itself (``web.perf_marks.boot``) rather than threading params.
 */

/** @typedef {boolean | number | string | null} FeatureFlagValue */

/**
 * Options object for {@link featureFlag}. ``default`` is the value
 * returned when no source provides one; ``description`` is metadata
 * used by tooling (e.g. the future dev overlay) and ignored at runtime.
 *
 * @typedef {{
 *   default?: FeatureFlagValue;
 *   description?: string;
 * }} FeatureFlagOptions
 */

const LS_PREFIX = "feature.";
const URL_PARAM_NAME = "features";

/**
 * Parse a raw string token from URL or localStorage into a typed value.
 * Matches the convention used by ``debug=`` params: bare-name tokens are
 * truthy, ``true`` / ``false`` / ``null`` parse to their literal values,
 * numeric strings parse to numbers, and everything else stays a string.
 *
 * @param {string} raw
 * @returns {FeatureFlagValue}
 */
function _parseValue(raw) {
    if (raw === "true") {
        return true;
    }
    if (raw === "false") {
        return false;
    }
    if (raw === "null") {
        return null;
    }
    const trimmed = raw.trim();
    if (trimmed === "") {
        // Empty string after a colon (``name:``) — treat as boolean true so
        // a flag toggle still works when the operator forgets the value.
        return true;
    }
    const n = Number(trimmed);
    if (Number.isFinite(n) && /^-?(\d+\.?\d*|\.\d+)$/.test(trimmed)) {
        return n;
    }
    return raw;
}

/**
 * Cached URL overrides. ``null`` means "not yet read"; an empty Map
 * means "read but URL had no features param".
 *
 * @type {Map<string, FeatureFlagValue> | null}
 */
let _urlOverrides = null;

/**
 * Tokenise a ``features=`` URL param value into a name→value map.
 *
 * Accepted entry shapes:
 *
 *   ``name``        -> ``true``
 *   ``-name``       -> ``false``
 *   ``name:value``  -> parsed via {@link _parseValue}
 *
 * Separators: ``,`` and ``;`` are both accepted so callers can pick
 * whichever doesn't clash with their other URL params.
 *
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
 * Lazy-read and cache URL overrides. The cache is module-scoped so a
 * page reload picks up new URL params naturally.
 *
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
    } catch {
        // Sandboxed iframe or non-standard scheme — silently ignore;
        // the cache stays an empty Map so we don't retry on every call.
    }
    return _urlOverrides;
}

/**
 * Read a single flag from ``localStorage``. Returns ``undefined`` if
 * the key is missing or the storage backend throws (private mode,
 * sandboxed iframe). The undefined sentinel — distinct from
 * ``null`` or ``false`` — lets callers continue down the cascade.
 *
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
 * Read a single flag from the server-emitted ``session.feature_flags``
 * dict. Returns ``undefined`` if the dict is absent or the key is
 * missing — same cascade-fall-through semantics as the LS reader.
 *
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
 * Resolve a feature flag through the four-step cascade.
 *
 * @param {string} name Flag identifier (snake_case by convention).
 * @param {FeatureFlagOptions} [options]
 * @returns {FeatureFlagValue}
 */
export function featureFlag(name, options = {}) {
    const urlOverrides = _getUrlOverrides();
    if (urlOverrides.has(name)) {
        return /** @type {FeatureFlagValue} */ (urlOverrides.get(name));
    }
    const fromLs = _readLocalStorage(name);
    if (fromLs !== undefined) {
        return fromLs;
    }
    const fromServer = _readServer(name);
    if (fromServer !== undefined) {
        return fromServer;
    }
    return options.default ?? false;
}

/**
 * Persist a feature flag override to ``localStorage`` so it survives
 * reload. Intended for use from the browser console / developer
 * overlay — production code should NOT write flags at runtime.
 *
 * @param {string} name
 * @param {FeatureFlagValue} value
 */
export function setFeatureFlag(name, value) {
    try {
        browser.localStorage?.setItem(LS_PREFIX + name, String(value));
    } catch {
        // ignore — private mode, quota, sandbox, etc.
    }
}

/**
 * Remove a previously-persisted flag, falling back to whatever the
 * URL / server / default cascade resolves next time.
 *
 * @param {string} name
 */
export function clearFeatureFlag(name) {
    try {
        browser.localStorage?.removeItem(LS_PREFIX + name);
    } catch {
        // ignore
    }
}

/**
 * Reset the URL-override cache. Tests use this so a stubbed
 * ``window.location`` is re-read on the next ``featureFlag(...)`` call.
 * Production code should not call this — page reload is the upgrade
 * path for URL params.
 */
export function _resetFeatureFlagsCache() {
    _urlOverrides = null;
}

/**
 * Return a snapshot of every flag the resolver currently knows about,
 * together with the source that resolved it. Intended for diagnostic
 * UI (debug overlay, ``?debug=features`` panel) — never load-bearing.
 *
 * @returns {Array<{ name: string; value: FeatureFlagValue; source: "url" | "localStorage" | "server"; }>}
 */
export function getFeatureFlagsSnapshot() {
    /** @type {{ name: string; value: FeatureFlagValue; source: "url" | "server" | "localStorage" }[]} */
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
    } catch {
        // ignore
    }
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
