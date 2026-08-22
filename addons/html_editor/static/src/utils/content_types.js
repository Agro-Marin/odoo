/** @odoo-module native */
export const CTYPES = {
    CONTENT: 1,
    SPACE: 2,

    BLOCK_OUTSIDE: 4,
    BLOCK_INSIDE: 8,

    BR: 16,
};
export function ctypeToString(ctype) {
    return Object.keys(CTYPES).find((key) => CTYPES[key] === ctype);
}
export const CTGROUPS = {
    INLINE: CTYPES.CONTENT | CTYPES.SPACE,
    BLOCK: CTYPES.BLOCK_OUTSIDE | CTYPES.BLOCK_INSIDE,
    BR: CTYPES.BR,
};
