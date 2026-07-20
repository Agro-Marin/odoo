/** @odoo-module native */

/**
 * Pure, DOM-free helpers shared by the fullscreen player and quiz widgets.
 *
 * They live in their own dependency-free module (no publicWidget, no jQuery, no
 * template coupling) so they can be unit-tested in isolation — the widgets that
 * use them pull in the whole legacy frontend stack, which is why the logic that
 * broke in the jQuery→native migration had no unit coverage and shipped.
 */

/**
 * Dataset keys that carry a boolean, whatever the server-side spelling.
 *
 * The fullscreen templates emit these three ways depending on the branch:
 * ``1``/``0`` (t-att with an int expression), ``true``/``false`` (values that
 * round-trip through JSON) and ``True``/``False`` (a raw Python bool). They all
 * arrive as strings via ``dataset``, and every non-empty string is truthy — so
 * ``!slide.completed`` was false for a *non*-completed slide.
 */
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
 * @param {string|boolean} value a raw dataset value
 * @returns {boolean}
 */
export function parseSlideBoolean(value) {
    return value === true || value === "1" || value === "true" || value === "True";
}

/**
 * Build a plain, correctly-typed slide object out of a sidebar item dataset.
 *
 * Returning a copy (rather than the live ``DOMStringMap``) also stops later
 * writes such as ``slide.htmlContent = ...`` from leaking back into the DOM as
 * stray ``data-*`` attributes.
 *
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
 * Get the slide dict matching the given criteria.
 *
 * Matching is strict, which is only sound because every slide has been put
 * through ``parseSlideDataset`` first — comparing a parsed ``id`` (Number)
 * against a raw ``dataset.id`` (String) silently matches nothing.
 *
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
 * Turn server-rendered question markup into a real element.
 *
 * ``/slides/slide/quiz/question_add_or_update`` returns an ``ir.qweb`` render.
 * Markup does not survive JSON-RPC, so it arrives as a plain string, and the DOM
 * insertion methods (``after``/``prepend``/``replaceWith``) turn a string into a
 * *Text node* — the publisher saw escaped HTML source instead of the question.
 * Parsing is safe: the payload is server-generated, same trust level as the
 * surrounding server-side render.
 *
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
