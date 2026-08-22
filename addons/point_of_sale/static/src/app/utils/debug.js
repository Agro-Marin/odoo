/** @odoo-module native */
/* eslint-disable no-console -- developer debug utility */
/**
 * @param {Object} obj
 * @param {number} [depth=0]
 * @param {number} [maxDepth=2]
 * @returns {Object|Array}
 */
function buildRepresentativeObject(obj, depth = 0, maxDepth = 2) {
    if (depth > maxDepth || obj === null || typeof obj !== "object") {
        return obj;
    }
    const result = Array.isArray(obj) ? [] : {};
    for (const key in obj) {
        if (Object.hasOwn(obj, key)) {
            try {
                const value = obj[key];
                if (typeof value === "object" && value !== null) {
                    result[key] = buildRepresentativeObject(value, depth + 1, maxDepth);
                } else {
                    result[key] = value;
                }
            } catch (error) {
                result[key] = `Error: ${error.message}`;
            }
        }
    }
    return result;
}

/**
 * @param {Object} obj
 * @param {number} [depth=0]
 * @param {number} [maxDepth=2]
 */
function log(obj, depth = 0, maxDepth = 2) {
    return console.log(buildRepresentativeObject(obj, depth, maxDepth));
}

/**
 * @param {Object} obj1
 * @param {Object} obj2
 * @param {Map} [visited=new Map()]
 * @param {number} [depth=0]
 * @param {number} [maxDepth=10]
 * @returns {Object}
 */
function compareObjects(obj1, obj2, visited = new Map(), depth = 0, maxDepth = 10) {
    if (depth > maxDepth) {
        return { error: "Profondeur de comparaison maximale atteinte." };
    }
    if (visited.has(obj1) || visited.has(obj2)) {
        return visited.get(obj1) === visited.get(obj2)
            ? {}
            : { error: "Référence circulaire détectée." };
    }
    visited.set(obj1, depth);
    visited.set(obj2, depth);
    const differences = {};
    const allKeys = new Set([...Object.keys(obj1), ...Object.keys(obj2)]);
    allKeys.forEach((key) => {
        const val1 = obj1[key];
        const val2 = obj2[key];
        if (typeof val1 !== typeof val2 || val1 !== val2) {
            if (val1 && val2 && typeof val1 === "object" && typeof val2 === "object") {
                const subDiff = compareObjects(
                    val1,
                    val2,
                    visited,
                    depth + 1,
                    maxDepth,
                );
                if (Object.keys(subDiff).length > 0) {
                    differences[key] = subDiff;
                }
            } else {
                differences[key] = { obj1: val1, obj2: val2 };
            }
        }
    });
    return buildRepresentativeObject(differences);
}

export const debug = {
    compareObjects,
    buildRepresentativeObject,
    log,
};
