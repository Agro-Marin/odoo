import { expect } from "@odoo/hoot";

import { testEditor } from "./editor.js";

export const TAB_WIDTH = 40;

let charWidths = undefined;
let indentWidths = undefined;
let widthsPromise = undefined;

function setWidths() {
    if (!widthsPromise) {
        widthsPromise = measureWidths();
    }
    return widthsPromise;
}

async function measureWidths() {
    charWidths = {};
    indentWidths = {};

    const rootDiv = document.createElement("div");
    rootDiv.classList.add("odoo-editor-editable");
    rootDiv.contentEditable = true;
    document.body.append(rootDiv);

    const referenceBlock = document.createElement("p");
    rootDiv.append(referenceBlock);

    const range = new Range();
    const tags = ["p", "h1", "blockquote", "li"];
    const chars = ["a", "b", "c", "d", "e", "f"];

    const elements = {};
    for (const tag of tags) {
        let element;
        if (tag === "li") {
            const ul = document.createElement("ul");
            element = document.createElement("li");
            ul.append(element);
            rootDiv.append(ul);
        } else {
            element = document.createElement(tag);
            rootDiv.append(element);
        }
        element.textContent = "|";
        elements[tag] = element;
    }

    await document.fonts.ready;

    const referenceLeft = referenceBlock.getBoundingClientRect().left;
    for (const tag of tags) {
        const element = elements[tag];

        element.textContent = "|";
        range.selectNodeContents(element);
        indentWidths[tag] = range.getBoundingClientRect().left - referenceLeft;

        charWidths[tag] = {};
        for (const char of chars) {
            element.textContent = char;
            range.selectNodeContents(element);
            charWidths[tag][char] = range.getBoundingClientRect().width;
        }
    }
    rootDiv.remove();
}

export async function getCharWidth(tag, char) {
    await setWidths();
    return charWidths[tag][char];
}

export async function getIndentWidth(tag) {
    await setWidths();
    return indentWidths[tag];
}

export function oeTab(size, contenteditable = true) {
    return (
        `<span class="oe-tabs"` +
        (contenteditable ? "" : ' contenteditable="false"') +
        (size ? ` style="width: ${Number(size.toFixed(1))}px;"` : "") +
        `>\u0009</span>\u200B`
    );
}

/**
 * @param {string} content
 * @returns {Object}
 */
function extractWidth(content) {
    const regex = /width: ([\d.]+)px;/g;
    const widths = [];
    const text = content.replaceAll(regex, (_, w) => {
        widths.push(parseFloat(w));
        return `width: _px;`;
    });
    return { text, widths };
}

/**
 * @param {string} contentEl
 * @param {string} contentSpec
 * @param {"contentAfterEdit"|"contentAfter"} mode
 */
function compare(contentEl, contentSpec, mode) {
    const maxDiff = 0.5;
    const { text: receivedContent, widths: receivedWidths } = extractWidth(contentEl);
    const { text: expectedContent, widths: expectedWidths } = extractWidth(contentSpec);

    expect(receivedContent).toBe(expectedContent, {
        message: `(testEditor) ${mode} should be strictly equal to ${expectedContent}`,
    });

    const diffs = expectedWidths.map((width, i) => Math.abs(width - receivedWidths[i]));
    expect(Math.max(...diffs)).toBeLessThan(maxDiff, {
        message:
            `(testEditor) (${mode}) tab widths differ by less than ${maxDiff} pixel\n` +
            diffs
                .map(
                    (diff, i) =>
                        `tab[${i}] ` +
                        `received: ${receivedWidths[i]}, ` +
                        `expected: ${expectedWidths[i]}, ` +
                        `diff: ${diff.toFixed(1)}`,
                )
                .join("\n"),
    });
}

export function testTabulation(params) {
    return testEditor({ ...params, compareFunction: compare });
}
