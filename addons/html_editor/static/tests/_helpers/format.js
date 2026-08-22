const OPENING_TAG_REGEX = /<\s*([^\s/>]+)([^>]*?)(\/?)>/g;
const ATTRIBUTES_REGEX = /([^\s=]+)(=(?:"[^"]*"|'[^']*'))?/g;

export function unformat(html) {
    return (
        html
            .replace(OPENING_TAG_REGEX, (match, tag, attrs, selfClosing) => {
                const attributes = attrs.match(ATTRIBUTES_REGEX);
                return `<${tag}${attributes ? " " + attributes.join(" ") : ""}${selfClosing}>`;
            })
            .replace(/>[^\S\uFEFF]+/g, ">")
            .replace(/[^\S\uFEFF]+</g, "<")
            .trim()
    );
}

/**
 * @param {string} html
 */
export function cleanLinkArtifacts(html) {
    return html.replaceAll("\uFEFF", "").replace(/ class="o_link_in_selection"/g, "");
}
