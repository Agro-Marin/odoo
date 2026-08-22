// @ts-check
/** @odoo-module native */

/**
 * @param {{ data: Record<string, any>, fields: Record<string, any> }} record
 * @param {string} [fullName]
 * @returns {string | undefined}
 */
export function getSignatureDefaultName(record, fullName) {
    if (!fullName) {
        return "";
    }
    const value = record.data[fullName];
    const signName =
        record.fields[fullName].type === "many2one" ? value?.display_name : value;
    return signName || undefined;
}
