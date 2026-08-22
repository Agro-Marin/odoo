// @ts-check
/** @odoo-module native */

const X2M_TYPES = ["one2many", "many2many"];

/**
 * @param {string} type
 * @returns {boolean}
 */
export function isX2ManyType(type) {
    return X2M_TYPES.includes(type);
}

/**
 * @param {{ type?: string } | null | undefined} field
 * @returns {boolean}
 */
export function isX2Many(field) {
    return Boolean(field) && isX2ManyType(/** @type {any} */ (field).type);
}
