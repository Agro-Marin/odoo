/** @odoo-module native */
/** @typedef {typeof import("@web/model/relational_model/record").RelationalRecord} RelationalModelRecord */

const SAFE_URL_SCHEME = /^(https?|ftp):\/\//;

/**
 * @param {String} url
 * @return {String}
 */
export function toSafeDocumentUrl(url) {
    return SAFE_URL_SCHEME.test(url) ? url : `http://${url}`;
}

/**
 * @param {String} url
 */
export function openDocumentUrl(url) {
    window.open(toSafeDocumentUrl(url), "_blank", "noopener,noreferrer");
}

/**
 * @param {number|String|false} userFolderId
 * @returns {number|String|false}
 */
export function toFolderValueId(userFolderId) {
    if (typeof userFolderId === "number") {
        return userFolderId;
    }
    if (typeof userFolderId !== "string" || !userFolderId) {
        return false;
    }
    return /^\d+$/.test(userFolderId) ? Number(userFolderId) : userFolderId;
}

/**
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
