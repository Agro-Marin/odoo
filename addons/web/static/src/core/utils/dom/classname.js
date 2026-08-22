// @ts-check
/** @odoo-module native */

/**
 * @param {HTMLElement} el
 * @param {...(string | object | undefined)} classes
 */
export function addClassesToElement(el, ...classes) {
    for (const classDefinition of classes) {
        const classObj = toClassObj(classDefinition);
        for (const className of Object.keys(classObj)) {
            if (classObj[className]) {
                el.classList.add(className.trim());
            }
        }
    }
}

/**
 * @param {...(string | object | undefined)} classes
 * @returns {object}
 */
export function mergeClasses(...classes) {
    const classObj = {};
    for (const classDefinition of classes) {
        Object.assign(classObj, toClassObj(classDefinition));
    }
    return classObj;
}

/**
 * @param {string | object | undefined} classDefinition
 * @returns {Record<string, any>}
 */
function toClassObj(classDefinition) {
    if (!classDefinition) {
        return {};
    } else if (typeof classDefinition === "object") {
        return classDefinition;
    } else if (typeof classDefinition === "string") {
        /** @type {Record<string, any>} */
        const classObj = {};
        for (const s of classDefinition.trim().split(/\s+/)) {
            classObj[s] = true;
        }
        return classObj;
    } else {
        console.warn(
            `toClassObj only supports strings, objects and undefined className (got ${typeof classDefinition})`,
        );
        return {};
    }
}
