// @ts-check

// ! WARNING: this module cannot depend on modules not ending with ".hoot" (except libs) !

/**
 * Per-element placeholder a template's `src` is rewritten to during tests,
 * so the browser's native image loader doesn't fire HTTP requests. A 1×1
 * fuchsia PNG: small, deterministic, harmless if it accidentally renders.
 */
const ONE_FUSCHIA_PIXEL_IMG =
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z9DwHwAGBQKA3H7sNwAAAABJRU5ErkJggg==";

/**
 * Tag-name → `src`-replacement pairs. `<iframe>` gets an empty `src` (no
 * document loaded); `<img>` gets the 1px placeholder.
 */
const SRC_REPLACERS = [
    ["iframe", ""],
    ["img", ONE_FUSCHIA_PIXEL_IMG],
];

/**
 * Owl's `src`-binding forms: `t-att-` (single binding, e.g.
 * `t-att-src="expr"`), `t-attf-` (interpolation, e.g.
 * `t-attf-src="prefix-{{var}}"`), and the literal attribute. Handled
 * uniformly so any author style is covered.
 */
const ATTRIBUTE_PREFIXES = ["", "t-att-", "t-attf-"];

/**
 * Strip `src` (and `t-att-src` / `t-attf-src`) from `<img>` / `<iframe>`
 * elements, moving the original value to `data-src` and replacing the
 * visible `src` with a deterministic placeholder. Tests assert against
 * `data-src` to verify the URL that would have been requested.
 *
 * `<img src=...>` HTTP requests bypass the JS `_onRoute` mock in
 * `mock_server.js` — Chrome's native image loader doesn't go through
 * `fetch`. Rewriting templates is the only way to keep the page fully
 * offline during tests.
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
 * Idempotent. Must run before any component mounts, so `setupTestEnvironment`
 * calls this after `start.hoot.js`'s top-level imports complete and before
 * the test loader starts importing test files. Clears the template cache in
 * case anything was already parsed (e.g. a forced render during module load).
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
