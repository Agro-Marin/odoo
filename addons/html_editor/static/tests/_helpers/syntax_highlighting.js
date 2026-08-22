import { LANGUAGES } from "@html_editor/others/embedded_components/backend/syntax_highlighting/code_toolbar";
import { EmbeddedSyntaxHighlightingComponent } from "@html_editor/others/embedded_components/backend/syntax_highlighting/syntax_highlighting";
import { DEFAULT_LANGUAGE_ID } from "@html_editor/others/embedded_components/core/syntax_highlighting/syntax_highlighting_utils";
import { expect } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-dom";
import { toExplicitString } from "@web/../lib/hoot/hoot_utils";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";

import { unformat } from "./format.js";

/** @typedef {import("@html_editor/editor").Editor} Editor */
/**
 * @typedef {Object} HighlightedContent
 * @property {string} value
 * @property {string} [language]
 * @property {number | [number, number]} [textareaRange = null]
 * @property {boolean} [wrapped = true]
 */
/**
 * @typedef {Object} FocusedTextarea
 * @property {HTMLTextAreaElement} el
 * @property {string} value
 * @property {number | [number, number]} range
 */

/**
 * @param {string} html
 * @param {string} [languageId = DEFAULT_LANGUAGE_ID]
 * @param {boolean} [ejectBr = false]
 * @returns {string}
 */
const highlight = (html, languageId = DEFAULT_LANGUAGE_ID, ejectBr = false) =>
    `<span id="${languageId}">${ejectBr ? html.replace(/((<br>)*)$/, "") : html}</span>${
        ejectBr ? html.match(/(?:<br>)+$/)?.[0] || "" : ""
    }`;

export const patchPrism = () => {
    patchWithCleanup(EmbeddedSyntaxHighlightingComponent.prototype, {
        async loadPrism() {
            window.Prism = {
                highlight: (html, l, languageId = DEFAULT_LANGUAGE_ID) =>
                    highlight(html, languageId),
                languages: {},
            };
        },
    });
};

/**
 * @param {Editor} editor
 * @param {FocusedTextarea} focusedTextarea
 * @param {string} [message]
 */
export const testTextareaRange = (editor, { el, value, range }, message) => {
    range = Array.isArray(range) ? range : [range];
    const start = range[0];
    const end = range.length > 1 ? range[1] : start;
    const { anchorNode, anchorOffset, focusNode, focusOffset } =
        editor.document.getSelection();
    expect({
        activeElement: editor.document.activeElement,
        anchorTarget: anchorNode.childNodes[anchorOffset],
        focusTarget: focusNode.childNodes[focusOffset],
        textareaValue: el.value,
        textareaRange: [el.selectionStart, el.selectionEnd],
    }).toEqual(
        {
            activeElement: el,
            anchorTarget: el,
            focusTarget: el,
            textareaValue: value,
            textareaRange: [start, end],
        },
        {
            message: `Selection should be correct in the textarea${message ? ":\n" + message : ""}`,
        },
    );
};

const TOOLBAR = (language) =>
    unformat(
        `<div class="o_code_toolbar">
        <div data-prevent-closing-overlay="true">
            <button class="btn o-dropdown dropdown-toggle dropdown" name="language" title="${language}" aria-expanded="false">
                <span class="px-1">${language}</span>
                <i class="fa-solid fa-caret-down"></i>
            </button>
            <button type="button" class="text-nowrap btn o_clipboard_button">
                <span class="mx-1 fa-solid fa-clipboard"></span>
                <span>Copy</span>
            </button>
            <button class="text-nowrap btn"><span class="mx-1 fa-solid fa-paragraph" title="Convert to paragraph"></span></button>
        </div>
    </div>`,
    );

/**
 * @param {string} content
 * @param {string} expected
 * @param {string} phase
 * @param {Editor} editor
 */
export const compareHighlightedContent = async (content, expected, phase, editor) => {
    let cleanedContent = content
        .replaceAll(/"stateChangeId":\d+/g, "")
        .replaceAll(/"previous":\{[^}]+\}/g, "")
        .replaceAll(/"next":\{([^}]+)\}/g, "$1")
        .replaceAll("data-embedded-state", "data-saved")
        .replaceAll(
            /"languageId":"([^"]*)","value":"(([^"]|\n)*)"/g,
            `"value":"$2","languageId":"$1"`,
        )
        .replaceAll(/([{,]),+/g, "$1")
        .replaceAll(/,+([},])/g, "$1")
        .replaceAll(",,", ",");

    cleanedContent = cleanedContent
        .split("data-embedded=")
        .map((currentSection) => {
            if (currentSection.includes("data-embedded-props")) {
                if (currentSection.includes("data-saved")) {
                    currentSection = currentSection.replaceAll(
                        /data-embedded-props='\{[^']+\}'( )?/g,
                        "",
                    );
                } else {
                    currentSection = currentSection.replaceAll(
                        "data-embedded-props",
                        "data-saved",
                    );
                }
            }
            return currentSection;
        })
        .join("data-embedded=");

    const message = `(testEditor) ${toExplicitString(
        phase,
    )} is strictly equal to "${toExplicitString(expected)}"`;
    await animationFrame();
    const strings = expected.split("<textarea");
    strings.shift();
    const textareaIndex = strings.findIndex((str) => str.startsWith("~~~"));
    if (textareaIndex !== -1) {
        const el = editor.editable.querySelectorAll("textarea")[textareaIndex];
        const [range, value] = strings[textareaIndex]
            .match(/~~~([^~]+)~~~/)[1]
            .split("°°°");
        const parsedRange = range
            .split(",")
            .map((v) => +v.replace(/[[\]]/g, "").trim());
        testTextareaRange(editor, { el, range: parsedRange, value }, message);
        expected = expected.replace(/<textarea~~~[^~]+~~~/g, "<textarea");
    }
    expect(cleanedContent).toBe(expected, { message });
};

export const highlightedPre = ({
    value,
    language = DEFAULT_LANGUAGE_ID,
    textareaRange = null,
    preHtml = value.replaceAll("\n", "<br>"),
}) =>
    unformat(
        `<div data-embedded="syntaxHighlighting" data-oe-protected="true" contenteditable="false"
            class="o_syntax_highlighting"
            data-saved='{"value":"${value.replaceAll(
                "\n",
                "\\n",
            )}","languageId":"${language.toLowerCase()}"}'>
            ${TOOLBAR(LANGUAGES[language])}
            <pre>//PRE//</pre>${textareaRange === null ? "" : "[]"}
            <textarea //TEXTAREA// class="o_prism_source" contenteditable="true"  placeholder="Code"></textarea>
        </div>`,
    )
        .replace("//PRE//", highlight(preHtml || "<br>", language, true))
        .replace(
            " //TEXTAREA// ",
            textareaRange ? "~~~" + textareaRange + "°°°" + value + "~~~ " : " ",
        );
