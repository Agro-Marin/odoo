/** @odoo-module native */
import { _t } from "@web/core/translation";
import { formatXML } from "@web/core/utils/dom/xml";

const MAPPING = {
    "{": "}",
    "}": "{",
    "(": ")",
    ")": "(",
    "[": "]",
    "]": "[",
};
const OPENINGS = ["{", "(", "["];
const CLOSINGS = ["}", ")", "]"];

/**
 * @param {string} scss
 * @returns {Object}
 */
export function checkSCSS(scss) {
    const stack = [];
    let line = 1;
    for (let i = 0; i < scss.length; i++) {
        if (OPENINGS.includes(scss[i])) {
            stack.push(scss[i]);
        } else if (CLOSINGS.includes(scss[i])) {
            if (stack.pop() !== MAPPING[scss[i]]) {
                return {
                    isValid: false,
                    error: {
                        line,
                        message: _t("Unexpected %(char)s", { char: scss[i] }),
                    },
                };
            }
        } else if (scss[i] === "\n") {
            line++;
        }
    }
    if (stack.length > 0) {
        return {
            isValid: false,
            error: {
                line,
                message: _t("Expected %(char)s", { char: MAPPING[stack.pop()] }),
            },
        };
    }
    return { isValid: true };
}

/**
 * @param {string} xml
 * @returns {Object}
 */
export function checkXML(xml) {
    const xmlDoc = new window.DOMParser().parseFromString(xml, "text/xml");
    const errorEls = xmlDoc.getElementsByTagName("parsererror");
    if (errorEls.length > 0) {
        const errorEl = errorEls[0];
        const sourceTextEls = errorEl.querySelectorAll("sourcetext");
        let codeEls = null;
        if (sourceTextEls.length) {
            codeEls = [...sourceTextEls].map((el) => {
                const codeEl = document.createElement("code");
                codeEl.textContent = el.textContent;
                const brEl = document.createElement("br");
                brEl.classList.add("o_we_source_text_origin");
                el.parentElement.insertBefore(brEl, el);
                return codeEl;
            });
            for (const el of sourceTextEls) {
                el.remove();
            }
        }
        for (const el of [...errorEl.querySelectorAll(":not(code):not(pre):not(br)")]) {
            const pEl = document.createElement("p");
            for (const cEl of [...el.childNodes]) {
                pEl.appendChild(cEl);
            }
            el.parentElement.insertBefore(pEl, el);
            el.remove();
        }
        errorEl.querySelectorAll(".o_we_source_text_origin").forEach((el, i) => {
            el.after(codeEls[i]);
        });
        const lineMatch = errorEl.innerHTML.match(/[Ll]ine[^\d]+(\d+)/);
        return {
            isValid: false,
            error: {
                line: lineMatch ? parseInt(lineMatch[1], 10) : 1,
                message: errorEl.textContent,
            },
        };
    }
    return { isValid: true };
}

/**
 * @param {string} xml
 * @param {number} [indent=4]
 * @returns {string}
 */
export function formatXMLSafe(xml, indent = 4) {
    if (/<script(?: [^>]*)?>[^<][\s\S]*<\/script>/i.test(xml)) {
        return xml;
    }
    return formatXML(xml, indent);
}

export { formatXML };
