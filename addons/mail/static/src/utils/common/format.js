/** @odoo-module native */
import { htmlEscape, markup } from "@odoo/owl";
import { loadEmoji, loader } from "@web/components/emoji_picker/emoji_picker";
import { router } from "@web/core/browser/router";
import { normalize } from "@web/core/l10n/utils";
import {
    createDocumentFragmentFromContent,
    createElementWithContent,
    htmlFormatList,
    htmlJoin,
    htmlReplace,
    htmlReplaceAll,
    htmlTrim,
    isHtmlEmpty,
    setElementContent,
} from "@web/core/utils/dom/html";
import { setAttributes } from "@web/core/utils/dom/xml";
import { escapeRegExp } from "@web/core/utils/format/strings";
import { getOrigin } from "@web/core/utils/urls";
const urlRegexp =
    /\b(?:https?:\/\/\d{1,3}(?:\.\d{1,3}){3}|(?:https?:\/\/|(?:www\.))[-a-z0-9@:%._+~#=\u00C0-\u024F\u1E00-\u1EFF]{1,256}(?:\.{1})?(?:[a-z]{2,13}))\b(?:[-a-z0-9@:%_+~#?&[\]^|{}`\\'$//=\u00C0-\u024F\u1E00-\u1EFF]|[.]*[-a-z0-9@:%_+~#?&[\]^|{}`\\'$//=\u00C0-\u024F\u1E00-\u1EFF]|,(?!$| )|\.(?!$| |\.)|;(?!$| ))*/gi;
// Lazy: with native ESM this module is evaluated eagerly at bundle load,
// before test tooling can mock the browser location, so capturing
// ``getOrigin()`` in a module-level constant would freeze the wrong origin.
let messageUrlRegExp;
let messageUrlRegExpOrigin;
function getMessageUrlRegExp() {
    const origin = getOrigin();
    if (messageUrlRegExpOrigin !== origin) {
        messageUrlRegExpOrigin = origin;
        messageUrlRegExp = new RegExp(
            `^${escapeRegExp(origin)}/mail/message/(\\d+)$`,
        );
    }
    return messageUrlRegExp;
}

/**
 * @param {string|ReturnType<markup>} rawBody
 * @param {Object} validMentions
 * @param {import("models").Persona[]} validMentions.partners
 * @returns {Promise<string|ReturnType<markup>>}
 */
export function prettifyMessageText(rawBody, { validMentions = {}, thread } = {}) {
    if (rawBody instanceof markup().constructor) {
        // markup is already "pretty"
        return rawBody;
    }
    let body = htmlTrim(rawBody);
    body = htmlReplace(body, /(\r|\n){2,}/g, () => markup`<br/><br/>`);
    body = htmlReplace(body, /(\r|\n)/g, () => markup`<br/>`);
    body = htmlReplace(body, /&nbsp;/g, () => " ");
    body = htmlTrim(body);
    // This message will be received from the mail composer as html content
    // subtype but the urls will not be linkified. If the mail composer
    // takes the responsibility to linkify the urls we end up with double
    // linkification a bit everywhere. Ideally we want to keep the content
    // as text internally and only make html enrichment at display time but
    // the current design makes this quite hard to do.
    body = generateMentionsLinks(body, { ...validMentions, thread });
    body = parseAndTransform(body, addLink);
    return body;
}

/**
 * @param {string|ReturnType<markup>} htmlBody
 */
export async function generateEmojisOnHtml(
    htmlBody,
    { allowEmojiLoading = true } = {},
) {
    let body = htmlBody;
    if (
        allowEmojiLoading ||
        loader.loaded
    ) {
        body = await _generateEmojisOnHtml(body);
    }
    return body;
}

/**
 * @param {string|ReturnType<markup>} rawBody
 * @param {Object} validMentions
 * @param {import("models").Persona[]} validMentions.partners
 */
export async function prettifyMessageContent(
    rawBody,
    { validMentions = [], allowEmojiLoading = true } = {},
) {
    let body = prettifyMessageText(rawBody, { validMentions });
    body = await generateEmojisOnHtml(body, { allowEmojiLoading });
    return body;
}

/**
 * WARNING: this is not enough to unescape potential XSS contained in htmlString, transformFunction
 * should handle it or it should be handled after/before calling parseAndTransform. So if the result
 * of this function is used in a t-raw, be very careful.
 *
 * @param {string|ReturnType<markup>} htmlString
 * @param {function} transformFunction
 * @returns {ReturnType<markup>}
 */
export function parseAndTransform(htmlString, transformFunction) {
    const div = document.createElement("div");
    try {
        setElementContent(div, htmlString);
    } catch {
        div.appendChild(createElementWithContent("pre", htmlString));
    }
    return _parseAndTransform(Array.from(div.childNodes), transformFunction);
}

/**
 * @param {Node[]} nodes
 * @param {function} transformFunction with:
 *   param node
 *   param function
 *   return string
 * @return {ReturnType<markup>}
 */
function _parseAndTransform(nodes, transformFunction) {
    if (!nodes) {
        return;
    }
    return htmlJoin(
        Object.values(nodes).map((node) =>
            transformFunction(node, function () {
                return _parseAndTransform(node.childNodes, transformFunction);
            }),
        ),
    );
}

/**
 * @param {string} text
 * @return {ReturnType<markup>} linkified text
 */
function linkify(text) {
    let curIndex = 0;
    let result = "";
    let match;
    while ((match = urlRegexp.exec(text)) !== null) {
        const url = match[0];
        const fixedUrl = !/^https?:\/\//i.test(url) ? `http://${url}` : url;
        if (!URL.canParse(fixedUrl)) {
            continue;
        }
        result = htmlJoin([result, text.slice(curIndex, match.index)]);
        const { href } = URL.parse(fixedUrl);
        const link = document.createElement("a");
        setAttributes(link, {
            target: "_blank",
            rel: "noreferrer noopener",
            href,
        });
        link.textContent = url;
        const messageMatch = getMessageUrlRegExp().exec(fixedUrl);
        if (messageMatch !== null) {
            setAttributes(link, {
                "data-oe-id": messageMatch[1],
                "data-oe-model": "mail.message",
            });
            link.classList.add("o_message_redirect");
        }
        // markup: outerHTML is safe when used as a node
        result = htmlJoin([result, markup(link.outerHTML)]);
        curIndex = match.index + match[0].length;
    }
    return htmlJoin([result, text.slice(curIndex)]);
}

/**
 * @param {Node} node
 * @param {function} transformFunction
 * @return {ReturnType<markup>}
 */
export function addLink(node, transformChildren) {
    if (node.nodeType === 3) {
        // text node
        const linkified = linkify(node.textContent);
        if (linkified.toString() !== node.textContent) {
            const div = createElementWithContent("div", linkified);
            for (const childNode of [...div.childNodes]) {
                node.parentNode.insertBefore(childNode, node);
            }
            node.parentNode.removeChild(node);
            return linkified;
        }
        return node.textContent;
    }
    if (node.tagName === "A") {
        return markup(node.outerHTML);
    }
    transformChildren();
    return markup(node.outerHTML);
}

function generateMentionElement({ className, id, model, text }) {
    const link = document.createElement("a");
    setAttributes(link, {
        href: router.stateToUrl({ model: model, resId: id }),
        class: className,
        "data-oe-id": id,
        "data-oe-model": model,
        target: "_blank",
        contenteditable: "false",
    });
    link.textContent = text;
    return link;
}

/**
 * @param {import("models").ResPartner} partner
 * @param {import("models").Thread} thread
 */
export function generatePartnerMentionElement(partner, thread) {
    return generateMentionElement({
        className: "o_mail_redirect",
        id: partner.id,
        model: "res.partner",
        text: `@${thread?.getPersonaName(partner) ?? partner.name}`,
    });
}

/** @param {import("models").ResRole} role */
export function generateRoleMentionElement(role) {
    return generateMentionElement({
        className: "o-discuss-mention",
        id: role.id,
        model: "res.role",
        text: `@${role.name}`,
    });
}

/** @param {string} label */
export function generateSpecialMentionElement(label) {
    const link = document.createElement("a");
    setAttributes(link, {
        class: "o-discuss-mention",
        contenteditable: "false",
    });
    link.textContent = `@${label}`;
    return link;
}

/** @param {import("models").Thread} thread */
export function generateThreadMentionElement(thread) {
    return generateMentionElement({
        className: `o_channel_redirect${
            thread.parent_channel_id ? " o_channel_redirect_asThread" : ""
        }`,
        id: thread.id,
        model: "discuss.channel",
        text: `#${thread.fullNameWithParent}`,
    });
}

/**
 * @param {string|ReturnType<markup>} body
 * @param {Object} param1
 * @param {import("models").ResPartner[]} param1.partners
 * @param {import("models").ResRole[]} param1.roles
 * @param {import("models").Thread[]} param1.threads
 * @param {string[]} param1.specialMentions
 * @param {import("models").Thread} param1.thread
 * @return {ReturnType<markup>}
 */
function generateMentionsLinks(
    body,
    { partners = [], roles = [], threads = [], specialMentions = [], thread },
) {
    const mentions = [];
    for (const partner of partners) {
        const placeholder = `@-mention-partner-${partner.id}`;
        const text = `@${thread?.getPersonaName(partner) ?? partner.name}`;
        mentions.push({
            link: generatePartnerMentionElement(partner, thread),
            placeholder,
        });
        body = htmlReplace(body, text, placeholder);
    }
    for (const thread of threads) {
        const placeholder = `#-mention-channel-${thread.id}`;
        const text = `#${thread.fullNameWithParent}`;
        mentions.push({
            link: generateThreadMentionElement(thread),
            placeholder,
        });
        body = htmlReplace(body, text, placeholder);
    }
    for (const special of specialMentions) {
        const text = `@${special}`;
        const placeholder = `@-mention-special-${special}`;
        mentions.push({
            link: generateSpecialMentionElement(special),
            placeholder,
        });
        body = htmlReplace(body, text, placeholder);
    }
    for (const role of roles) {
        const placeholder = `@-mention-role-${role.id}`;
        const text = `@${role.name}`;
        mentions.push({
            link: generateRoleMentionElement(role),
            placeholder,
        });
        body = htmlReplace(body, text, placeholder);
    }
    for (const mention of mentions) {
        const link = mention.link;
        // function replacer: a plain-string replacement would interpret "$&",
        // "$`", "$'"... inside the link HTML (e.g. from a display name) as
        // replacement patterns, splicing chunks of the body into the link.
        // markup: outerHTML is safe when used as a node
        body = htmlReplace(body, mention.placeholder, () => markup(link.outerHTML));
    }
    return htmlEscape(body);
}

/**
 * Cache for {@link _generateEmojisOnHtml}: one precompiled alternation regex
 * over all shortcode/emoticon sources instead of ~thousands of per-source
 * regexes rescanning the whole body on every message post/edit. Keyed on the
 * emoji list identity (`loadEmoji()` caches it; tests may reset it).
 *
 * @type {{
 *  emojis: unknown[],
 *  codepointsBySource: Map<string, string>,
 *  regex: RegExp|null,
 * }|undefined}
 */
let emojiSourceCache;

function getEmojiSourceCache(emojis) {
    if (emojiSourceCache?.emojis !== emojis) {
        /** @type {Map<string, string>} */
        const codepointsBySource = new Map();
        for (const emoji of emojis) {
            for (const source of [...emoji.shortcodes, ...emoji.emoticons]) {
                // Sources are matched against escaped HTML: escape them too
                // (e.g. the "<3" emoticon appears as "&lt;3" in the body).
                const escapedSource = htmlEscape(String(source)).toString();
                if (!codepointsBySource.has(escapedSource)) {
                    codepointsBySource.set(escapedSource, emoji.codepoints);
                }
            }
        }
        const alternation = [...codepointsBySource.keys()]
            .sort((source1, source2) => source2.length - source1.length) // longest match first
            .map(escapeRegExp)
            .join("|");
        emojiSourceCache = {
            emojis,
            codepointsBySource,
            regex: alternation
                ? new RegExp(`(\\s|^)(${alternation})(?=\\s|$|<)`, "g")
                : null,
        };
    }
    return emojiSourceCache;
}

/**
 * @private
 * @param {string|ReturnType<markup>} htmlString
 * @returns {Promise<ReturnType<markup>>}
 */
async function _generateEmojisOnHtml(htmlString) {
    const { emojis } = await loadEmoji();
    const { codepointsBySource, regex } = getEmojiSourceCache(emojis);
    if (regex) {
        htmlString = htmlReplace(
            htmlString,
            regex,
            (_, whitespace, source) => whitespace + codepointsBySource.get(source),
        );
    }
    return htmlEscape(htmlString);
}

/**
 * @param {string|ReturnType<markup>} body
 * @returns {ReturnType<markup>}
 */
export function getNonEditableMentions(body) {
    const doc = createDocumentFragmentFromContent(body);
    for (const block of doc.body.querySelectorAll(".o_mail_reply_hide")) {
        block.classList.remove("o_mail_reply_hide");
    }
    // for mentioned partner
    for (const mention of doc.body.querySelectorAll(".o_mail_redirect")) {
        mention.setAttribute("contenteditable", false);
    }
    // for mentioned channel
    for (const mention of doc.body.querySelectorAll(".o_channel_redirect")) {
        mention.setAttribute("contenteditable", false);
    }
    // for special mentions
    for (const mention of doc.body.querySelectorAll(".o-discuss-mention")) {
        mention.setAttribute("contenteditable", false);
    }
    return markup(doc.body.innerHTML);
}

/**
 * @param {string|ReturnType<markup>} htmlString
 * @returns {string}
 */
export function htmlToTextContentInline(htmlString) {
    htmlString = htmlReplace(htmlString, /<br\s*\/?>/gi, () => " ");
    const div = document.createElement("div");
    try {
        setElementContent(div, htmlString);
    } catch {
        div.appendChild(createElementWithContent("pre", htmlString));
    }
    return div.textContent
        .trim()
        .replace(/[\n\r]/g, "")
        .replace(/\s\s+/g, " ");
}

export function convertBrToLineBreak(str) {
    str = htmlReplace(str, /<br\s*\/?>/gi, () => "\n");
    return createDocumentFragmentFromContent(str).body.textContent;
}

/**
 * @param {string|ReturnType<markup>} content
 * @returns {ReturnType<markup>}
 */
export function trimEmptyBlocksAround(content) {
    if (isHtmlEmpty(content)) {
        return content;
    }
    const body = createDocumentFragmentFromContent(content).body;
    let changed = false;

    const removeNode = (node) => {
        node.remove();
        changed = true;
    };

    /** @typedef {"start" | "end"} BoundarySide */

    /**
     * @param {Element | null | undefined} element
     * @param {BoundarySide} side
     * @returns {ChildNode | null}
     */
    const getBoundaryChild = (element, side) => {
        if (!element) {
            return null;
        }
        return side === "start" ? element.firstChild : element.lastChild;
    };

    /**
     * @param {Element | null | undefined} element
     * @param {BoundarySide} side
     * @returns {Element | null}
     */
    const getBoundaryElement = (element, side) => {
        if (!element) {
            return null;
        }
        return side === "start" ? element.firstElementChild : element.lastElementChild;
    };

    const trimTextNodes = (element, side) => {
        let node = getBoundaryChild(element, side);
        while (node?.nodeType === Node.TEXT_NODE && !node.textContent.trim()) {
            removeNode(node);
            node = getBoundaryChild(element, side);
        }
    };

    const trimEmptyParagraphs = (side) => {
        trimTextNodes(body, side);
        let paragraph = getBoundaryElement(body, side);
        while (["P", "DIV"].includes(paragraph?.tagName) && isHtmlEmpty(paragraph.innerHTML)) {
            removeNode(paragraph);
            trimTextNodes(body, side);
            paragraph = getBoundaryElement(body, side);
        }
    };

    const trimBoundaryParagraph = (side) => {
        trimEmptyParagraphs(side);
        const paragraph = getBoundaryElement(body, side);
        if (!paragraph || !["P", "DIV"].includes(paragraph.tagName)) {
            return;
        }
        trimTextNodes(paragraph, side);
        let node = getBoundaryChild(paragraph, side);
        while (node?.nodeName === "BR") {
            removeNode(node);
            trimTextNodes(paragraph, side);
            node = getBoundaryChild(paragraph, side);
        }
        trimEmptyParagraphs(side);
        if (getBoundaryElement(body, side) !== paragraph) {
            trimBoundaryParagraph(side);
        }
    };
    trimBoundaryParagraph("start");
    trimBoundaryParagraph("end");
    // markup: innerHTML of the body is safe as it is generated from a DocumentFragment created from a trusted source and operations on body, the trim and removeNode, preserve it "safe".
    return changed ? markup(body.innerHTML) : content;
}

export function cleanTerm(term) {
    return typeof term === "string" ? normalize(term) : "";
}

/**
 * Parses text to find email: Tagada <address@mail.fr> -> [Tagada, address@mail.fr] or False
 *
 * @param {string} text
 * @returns {[string,string|boolean]|false}
 */
export function parseEmail(text) {
    if (!text) {
        return;
    }
    let result = text.match(/"?(.*?)"? <(.*@.*)>/);
    if (result) {
        const name = (result[1] || "").trim().replace(/(^"|"$)/g, "");
        return [name, (result[2] || "").trim()];
    }
    result = text.match(/(.*@.*)/);
    if (result) {
        return [String(result[1] || "").trim(), String(result[1] || "").trim()];
    }
    return [text, false];
}

const r = String.raw;
/**
 * Match Country Subdivision Flags.
 * Black Flag emoji + tag-encoded subdivision name + cancel tag
 * Example:
 * \uD83C\uDFF4 + [B] + [E] + [W] + [A] + [L] + [CANCEL] = Flag for Wallonia (BE-WAL)
 */
const SUBDIVISION_FLAG = r`\uD83C\uDFF4[\u{E0020}-\u{E007E}]+\u{E007F}`;
/**
 * Match Keycaps (e.g., 5\uFE0F\u20E3, #\uFE0F\u20E3).
 * Numpad character + Variation Selector-16 + Combining Enclosing Keycap
 */
const KEYCAP = r`[#*\d]\uFE0F\u20E3`;
const EMOJI_WITH_SKIN_TONE = r`\p{Emoji_Modifier_Base}\p{Emoji_Modifier}`;
/**
 * Match "regular" emojis.
 * iOS keyboard sometimes appends an extraneous Variation Selector-16, which the
 * optional \uFE0F accounts for.
 */
const EMOJI_PRESENTATION = r`\p{Emoji_Presentation}\uFE0F?`;
/**
 * Match "text-default" emojis (\u2603, \u2665, \u2602) that are followed by a Variation
 * Selector-16 (U+FE0F), enabling their emoji representation (\u2603 \u2192 \u2603\uFE0F).
 * Negative lookahead prevents matching incomplete keycap sequences.
 */
const QUALIFIED_TEXT = r`(?![#*\d])\p{Emoji}\uFE0F`;
const EMOJI = r`(?:${SUBDIVISION_FLAG}|${KEYCAP}|${EMOJI_WITH_SKIN_TONE}|${EMOJI_PRESENTATION}|${QUALIFIED_TEXT})`;
export const EMOJI_REGEX = new RegExp(
    r`\p{Regional_Indicator}{2}|` + // Regional Indicator pairs (e.g., \uD83C\uDDE7\uD83C\uDDEA)
        r`${EMOJI}(?:\u200d${EMOJI})*`, // Zero Width Joiner sequences (e.g., \uD83D\uDC68\u200d\uD83D\uDC69\u200d\uD83D\uDC67\u200d\uD83D\uDC66)
    "gu",
);

/**
 * Wrap emojis present in the given text with a title and return a safe HTML
 * string.
 *
 * @param {string|ReturnType<markup>} content
 * @returns {ReturnType<markup>}
 */
export function decorateEmojis(content) {
    if (!loader.loaded || !content) {
        return content;
    }
    const doc = createDocumentFragmentFromContent(content);
    const nodes = doc.evaluate(
        ".//text()",
        doc.body,
        null,
        XPathResult.UNORDERED_NODE_SNAPSHOT_TYPE,
        null,
    );
    for (let i = 0; i < nodes.snapshotLength; i++) {
        const node = nodes.snapshotItem(i);
        const span = document.createElement("span");
        setElementContent(
            span,
            htmlReplaceAll(node.textContent, loader.loaded.emojiRegex, (codepoints) =>
                markup(
                    `<span class="o-mail-emoji" title="${htmlFormatList(
                        loader.loaded.emojiValueToShortcodes[codepoints],
                        { style: "unit-narrow" },
                    )}">${htmlEscape(codepoints)}</span>`,
                ),
            ),
        );
        node.replaceWith(...span.childNodes);
    }
    return markup(doc.body.innerHTML);
}

/**
 * Converts an object of key/value to string, where object represents a attClass with OWL syntax object
 * and value is evaluation of each key.
 * Example: "attClassObjectToString({ a: 1, b: 0, c: 1 })" converts to "a c".
 */
export function attClassObjectToString(obj) {
    return Object.entries(obj)
        .filter(([_, val]) => val)
        .map(([key, _]) => key)
        .join(" ");
}
