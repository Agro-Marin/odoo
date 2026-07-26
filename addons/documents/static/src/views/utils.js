/** @odoo-module native */
/** @typedef {typeof import("@web/model/relational_model/record").RelationalRecord} RelationalModelRecord */

/**
 * Schemes a URL document is allowed to be opened with. Anything else (most
 * notably `javascript:`, `data:` and `vbscript:`, which would run in the
 * origin of the opener) is treated as a bare host and prefixed with `http://`.
 */
const SAFE_URL_SCHEME = /^(https?|ftp):\/\//;

/**
 * Normalize a documents.document URL into something safe to hand to
 * `window.open`. Mirrors the server-side hardening of the /document redirect.
 *
 * @param {String} url
 * @return {String}
 */
export function toSafeDocumentUrl(url) {
    return SAFE_URL_SCHEME.test(url) ? url : `http://${url}`;
}

/**
 * Open a documents.document URL in a new tab, with the scheme allowlist
 * applied and the opener detached (reverse tabnabbing).
 *
 * @param {String} url
 */
export function openDocumentUrl(url) {
    window.open(toSafeDocumentUrl(url), "_blank", "noopener,noreferrer");
}

/**
 * From multiple documents.document records, return the actions available on all of them.
 * @param {RelationalModelRecord[]} documents
 * @return {{id: Number, name: String}[]}
 */
export function getCommonEmbeddedActions(documents) {
    if (!documents?.length) {
        return [];
    }
    let embeddedActionsMap = new Map(
        documents[0].data.available_embedded_actions_ids?.records.map((rec) => [
            rec.resId,
            rec.data.display_name,
        ]) || []
    );
    for (const document of documents.slice(1)) {
        if (!embeddedActionsMap.size) {
            return [];
        }
        const newEmbeddedActionsMap = new Map();
        document.data.available_embedded_actions_ids.records.forEach((r) => {
            if (embeddedActionsMap.has(r.resId)) {
                newEmbeddedActionsMap.set(r.resId, r.data.display_name);
            }
        });
        embeddedActionsMap = newEmbeddedActionsMap;
    }
    const embeddedActionsArray = Array.from(embeddedActionsMap.entries());
    return embeddedActionsArray.map(([id, name]) => ({ id, name }));
}
