// @ts-check

const ONE_FUSCHIA_PIXEL_IMG =
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z9DwHwAGBQKA3H7sNwAAAABJRU5ErkJggg==";

const SRC_REPLACERS = [
    ["iframe", ""],
    ["img", ONE_FUSCHIA_PIXEL_IMG],
];

const ATTRIBUTE_PREFIXES = ["", "t-att-", "t-attf-"];

/**
 * @param {Element} template
 */
function replaceAttributes(template) {
    for (const [tagName, value] of SRC_REPLACERS) {
        for (const prefix of ATTRIBUTE_PREFIXES) {
            const targetAttribute = `${prefix}src`;
            const dataAttribute = `${prefix}data-src`;
            for (const element of template.querySelectorAll(
                `${tagName}[${targetAttribute}]`,
            )) {
                element.setAttribute(
                    dataAttribute,
                    element.getAttribute(targetAttribute),
                );
                if (prefix) {
                    element.removeAttribute(targetAttribute);
                }
                element.setAttribute("src", value);
            }
        }
    }
}

const mockTemplatesRegistered = new WeakSet();

/**
 * @param {{ modules: Map<string, any> }} loader
 */
export function setupMockTemplates(loader) {
    const templatesModule = loader.modules.get("@web/core/templates");
    if (!templatesModule?.registerTemplateProcessor) {
        return;
    }
    if (mockTemplatesRegistered.has(templatesModule)) {
        return;
    }
    templatesModule.registerTemplateProcessor(replaceAttributes);
    mockTemplatesRegistered.add(templatesModule);
}
