// @ts-check

// ! WARNING: this module cannot depend on modules not ending with ".hoot" (except libs) !

/**
 * Per-element placeholder a template's `src` should be rewritten to in
 * tests so the browser's native image loader doesn't fire HTTP requests
 * during a unit test.  A 1×1 fuchsia PNG: small, deterministic, harmless
 * if it accidentally renders.
 */
const ONE_FUSCHIA_PIXEL_IMG =
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z9DwHwAGBQKA3H7sNwAAAABJRU5ErkJggg==";

/**
 * Tag-name → `src`-replacement-value pairs.  `<iframe>` gets an empty
 * `src` (no document loaded); `<img>` gets the 1px placeholder.
 */
const SRC_REPLACERS = [
    ["iframe", ""],
    ["img", ONE_FUSCHIA_PIXEL_IMG],
];

/**
 * Owl supports two attribute-binding prefixes for templates:
 * - `t-att-` (single-binding, e.g. `t-att-src="expr"`)
 * - `t-attf-` (interpolation, e.g. `t-attf-src="prefix-{{var}}"`)
 * Plus the literal attribute itself (no prefix).  We rename all three
 * forms uniformly so any author style is handled.
 */
const ATTRIBUTE_PREFIXES = ["", "t-att-", "t-attf-"];

/**
 * Strip every `src` (and `t-att-src` / `t-attf-src`) from `<img>` /
 * `<iframe>` elements in the template, moving the original value to
 * `data-src` (resp. `t-att-data-src` / `t-attf-data-src`) and replacing
 * the visible `src` with a deterministic placeholder.  Tests assert
 * against `data-src` to verify the URL the component WOULD have
 * requested, without the browser actually fetching it.
 *
 * Why static placeholder + data-src instead of intercepting fetch?
 * `<img src=...>` HTTP requests bypass the JS `_onRoute` mock in
 * `mock_server.js` — Chrome's native image loader doesn't go through
 * `fetch`.  Rewriting the templates is the only way to keep the page
 * fully offline during tests.
 *
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

/**
 * Register the `src → data-src` template processor on
 * `@web/core/templates` so it runs at parse time for every template.
 *
 * Idempotent — pushes the processor once.  Must be called BEFORE any
 * component mounts (so the processor is in `templateProcessors` when
 * `_getTemplate` first parses a template).  `setupTestEnvironment`
 * invokes this after `start.hoot.js`'s top-level imports complete and
 * before the test loader starts importing test files.
 *
 * If templates were already processed (e.g. someone forced a render
 * during module load), the cache is cleared so they're re-parsed with
 * the processor in effect.
 *
 * @param {{ modules: Map<string, any> }} loader
 */
// Once-guard keyed by the templates module object itself. In debug mode
// (`?debug=assets`) `loader.modules.get(...)` holds a REAL frozen ES-module
// namespace — writing a marker property onto it throws TypeError — so the
// guard must live outside the module object.
const mockTemplatesRegistered = new WeakSet();

export function setupMockTemplates(loader) {
    const templatesModule = loader.modules.get("@web/core/templates");
    if (!templatesModule?.registerTemplateProcessor) {
        return;
    }
    if (mockTemplatesRegistered.has(templatesModule)) {
        return;
    }
    templatesModule.registerTemplateProcessor(replaceAttributes);
    if (typeof templatesModule.clearProcessedTemplates === "function") {
        templatesModule.clearProcessedTemplates();
    }
    mockTemplatesRegistered.add(templatesModule);
}
