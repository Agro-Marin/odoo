import { describe, expect, test } from "@odoo/hoot";
import {
    findSlide,
    getDocumentMaxPage,
    parseQuestionMarkup,
    parseSlideBoolean,
    parseSlideDataset,
} from "@website_slides/js/public/slides_course_utils";

describe.current.tags("headless");

test("parseSlideBoolean coerces every server spelling, including falsey ones", () => {
    for (const truthy of ["1", "true", "True", true]) {
        expect(parseSlideBoolean(truthy)).toBe(true, {
            message: `${JSON.stringify(truthy)} must be true`,
        });
    }
    for (const falsey of ["0", "false", "False", "", undefined, null, false]) {
        expect(parseSlideBoolean(falsey)).toBe(false, {
            message: `${JSON.stringify(falsey)} must be false`,
        });
    }
});

test("parseSlideDataset yields a numeric id and real booleans", () => {
    const slide = parseSlideDataset({
        id: "42",
        isQuiz: "false",
        completed: "1",
        hasNext: "True",
        name: "Intro",
    });
    expect(slide.id).toBe(42);
    expect(typeof slide.id).toBe("number");
    expect(slide.completed).toBe(true);
    expect(slide.isQuiz).toBe(false);
    expect(slide.hasNext).toBe(true);
    expect(slide.name).toBe("Intro");
});

test("parseSlideDataset returns a copy, not the live DOMStringMap", () => {
    const dataset = { id: "7", name: "A" };
    const slide = parseSlideDataset(dataset);
    slide.htmlContent = "<p>hi</p>";
    expect(dataset.htmlContent).toBe(undefined);
});

test("findSlide matches normalised slides by id and quiz flag", () => {
    const slides = [
        parseSlideDataset({ id: "10", isQuiz: "false" }),
        parseSlideDataset({ id: "11", isQuiz: "1" }),
    ];
    expect(findSlide(slides, { id: 11, isQuiz: true })).toBe(slides[1]);
    expect(findSlide(slides, { id: 10, isQuiz: false })).toBe(slides[0]);
    expect(findSlide(slides, { id: "10", isQuiz: "false" })).toBe(undefined);
});

test("parseQuestionMarkup turns server markup into an element, not a text node", () => {
    const node = parseQuestionMarkup(
        '<p class="o_wslides_js_lesson_quiz_question">Q?</p>',
    );
    expect(node.nodeType).toBe(Node.ELEMENT_NODE);
    expect(node.classList.contains("o_wslides_js_lesson_quiz_question")).toBe(true);
    expect(node.textContent).toBe("Q?");
});

test("parseQuestionMarkup passes an existing node through untouched", () => {
    const el = document.createElement("div");
    expect(parseQuestionMarkup(el)).toBe(el);
});

test("parseSlideDataset normalises emailSharing, so `=== 'True'` cannot work", () => {
    const slide = parseSlideDataset({ id: "7", emailSharing: "True" });
    expect(slide.emailSharing).toBe(true);
    expect(slide.emailSharing === "True").toBe(false);
});

test("getDocumentMaxPage returns undefined rather than throwing when the viewer is absent", () => {
    const doc = document.implementation.createHTMLDocument("empty");
    expect(getDocumentMaxPage(doc)).toBe(undefined);
});

test("getDocumentMaxPage returns undefined when the iframe carries no page count", () => {
    const doc = document.implementation.createHTMLDocument("no-count");
    const iframe = doc.createElement("iframe");
    iframe.className = "o_wslides_iframe_viewer";
    doc.body.appendChild(iframe);
    expect(getDocumentMaxPage(doc)).toBe(undefined);
});
