/** @odoo-module native */
export const SLIDE_BOOLEAN_KEYS = [
    "isQuiz",
    "hasNext",
    "isMember",
    "isMemberOrInvited",
    "hasQuestion",
    "completed",
    "canAccess",
    "canSelfMarkCompleted",
    "canSelfMarkUncompleted",
    "emailSharing",
    "_autoSetDone",
];

/**
 * @param {string|boolean} value
 * @returns {boolean}
 */
export function parseSlideBoolean(value) {
    return value === true || value === "1" || value === "true" || value === "True";
}

/**
 * @param {DOMStringMap|Object} dataset
 * @returns {Object}
 */
export function parseSlideDataset(dataset) {
    const slide = { ...dataset };
    slide.id = Number(dataset.id);
    for (const key of SLIDE_BOOLEAN_KEYS) {
        if (key in slide) {
            slide[key] = parseSlideBoolean(slide[key]);
        }
    }
    return slide;
}

/**
 * @param {Array<Object>} slideList
 * @param {Object} matcher
 * @returns {Object|undefined}
 */
export function findSlide(slideList, matcher) {
    return slideList.find((slide) =>
        Object.keys(matcher).every((key) => matcher[key] === slide[key]),
    );
}

/**
 * @param {string|Node} rendered
 * @returns {Node}
 */
export function parseQuestionMarkup(rendered) {
    if (rendered instanceof Node) {
        return rendered;
    }
    const template = document.createElement("template");
    template.innerHTML = String(rendered).trim();
    return template.content.firstElementChild || template.content;
}

/**
 * @param {Document} [doc]
 * @returns {number|undefined}
 */
export function getDocumentMaxPage(doc = document) {
    const iframe = doc.querySelector("iframe.o_wslides_iframe_viewer");
    const pageCount = iframe?.contentWindow?.document?.querySelector("#page_count");
    const parsed = parseInt(pageCount?.innerText, 10);
    return Number.isNaN(parsed) ? undefined : parsed;
}
