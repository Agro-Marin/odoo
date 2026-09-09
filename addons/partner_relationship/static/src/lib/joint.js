// @ts-check
/** @odoo-module native */

let joint = null;
let loadPromise = null;

export function loadJoint() {
    loadPromise ??= import("joint")
        .then((module) => {
            joint = module;
            return module;
        })
        .catch((error) => {
            loadPromise = null;
            throw error;
        });
    return loadPromise;
}

export function jointLib() {
    if (joint === null) {
        throw new Error(
            "jointLib() called before loadJoint() resolved -- await it first.",
        );
    }
    return joint;
}
