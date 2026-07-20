import { describe, expect, test } from "@odoo/hoot";
import {
    findSlide,
    parseQuestionMarkup,
    parseSlideBoolean,
    parseSlideDataset,
} from "@website_slides/js/public/slides_course_utils";

describe.current.tags("headless");

// The fullscreen templates spell booleans three ways ("1"/"0", "true"/"false",
// "True"/"False") and everything reaches JS as a string via dataset, where every
// non-empty string is truthy. Before normalisation, `!slide.completed` was false
// for a NON-completed slide.
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
    // Writing computed content back must not leak into the source dataset.
    expect(dataset.htmlContent).toBe(undefined);
});

// findSlide matches strictly; it only works because slides are normalised first.
// This is the concrete bug: a parsed id (Number) never === a raw dataset id
// (String), so sidebar clicks and arrow-key nav silently found nothing.
test("findSlide matches normalised slides by id and quiz flag", () => {
    const slides = [
        parseSlideDataset({ id: "10", isQuiz: "false" }),
        parseSlideDataset({ id: "11", isQuiz: "1" }),
    ];
    // matcher built from parseInt/boolean, mirroring the click/key handlers
    expect(findSlide(slides, { id: 11, isQuiz: true })).toBe(slides[1]);
    expect(findSlide(slides, { id: 10, isQuiz: false })).toBe(slides[0]);
    // control: a raw-string id (the pre-fix mismatch) finds nothing
    expect(findSlide(slides, { id: "10", isQuiz: "false" })).toBe(undefined);
});

// The quiz question route returns Markup that JSON-RPC flattens to a string;
// DOM insertion of a string makes a Text node, so the publisher saw escaped
// HTML source. parseQuestionMarkup must return a real element.
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
