/** @odoo-module native */
export const fonts = {
    /**
     * Retrieves all the CSS rules which match the given parser (Regex).
     *
     * @param {Regex} filter
     * @param {Object} [options]
     * @param {string} [options.requiredProperty] - If set, only rules whose
     *     CSS text contains this property name are included. Used to filter
     *     FA7 icon rules (which set `--fa:`) from utility classes.
     * @returns {Object[]} Array of CSS rules descriptions (objects). A rule is
     *          defined by 3 values: 'selector', 'css' and 'names'. 'selector'
     *          is a string which contains the whole selector, 'css' is a string
     *          which contains the css properties and 'names' is an array of the
     *          first captured groups for each selector part. E.g.: if the
     *          filter is set to match .fa-* rules and capture the icon names,
     *          the rule:
     *              '.fa-heart { --fa: "\\f004"; }'
     *          will be retrieved as
     *              {
     *                  selector: '.fa-heart',
     *                  css: '--fa: "\\f004";',
     *                  names: ['fa-heart'],
     *              }
     */
    cacheCssSelectors: {},
    getCssSelectors(filter, { requiredProperty } = {}) {
        const cacheKey = `${filter}|${requiredProperty || ""}`;
        if (this.cacheCssSelectors[cacheKey]) {
            return this.cacheCssSelectors[cacheKey];
        }
        this.cacheCssSelectors[cacheKey] = [];
        const sheets = document.styleSheets;
        for (let i = 0; i < sheets.length; i++) {
            let rules;
            try {
                // try...catch because Firefox not able to enumerate
                // document.styleSheets[].cssRules[] for cross-domain
                // stylesheets.
                rules = sheets[i].rules || sheets[i].cssRules;
            } catch {
                continue;
            }
            if (!rules) {
                continue;
            }

            for (let r = 0; r < rules.length; r++) {
                const selectorText = rules[r].selectorText;
                if (!selectorText) {
                    continue;
                }
                if (requiredProperty && !rules[r].cssText.includes(requiredProperty)) {
                    continue;
                }
                const selectors = selectorText.split(/\s*,\s*/);
                let data = null;
                for (let s = 0; s < selectors.length; s++) {
                    const match = selectors[s].trim().match(filter);
                    if (!match) {
                        continue;
                    }
                    if (!data) {
                        data = {
                            selector: match[0],
                            css: rules[r].cssText.replace(/(^.*\{\s*)|(\s*\}\s*$)/g, ""),
                            names: [match[1]],
                        };
                    } else {
                        data.selector += ", " + match[0];
                        data.names.push(match[1]);
                    }
                }
                if (data) {
                    this.cacheCssSelectors[cacheKey].push(data);
                }
            }
        }
        return this.cacheCssSelectors[cacheKey];
    },
    /**
     * List of font icons to load by editor. The icons are displayed in the media
     * editor and identified like font and image (can be colored, spinned, resized
     * with fa classes).
     * To add font, push a new object {base, parser}
     *
     * - base: class that appears on all fonts of this family
     * - parser: regular expression used to select all font icons in css
     *           stylesheets. Must capture the icon class name as group 1.
     * - requiredProperty: if set, only CSS rules containing this property
     *                     are considered (filters out utility classes).
     *
     * FA7 uses CSS custom properties (`--fa`) instead of individual `::before`
     * rules, so the parser matches `.fa-xxx` selectors and the
     * `requiredProperty` filter ensures only icon definitions (not utility
     * classes like `.fa-spin` or `.fa-2x`) are included.
     *
     * @type Array
     */
    fontIcons: [
        { base: "fa-solid", parser: /^\.(fa-(?:\w|-)+)$/i, requiredProperty: "--fa:" },
    ],
    computedFonts: false,
    /**
     * Searches the fonts described by the @see fontIcons variable.
     */
    computeFonts() {
        if (!this.computedFonts) {
            for (const data of this.fontIcons) {
                data.cssData = this.getCssSelectors(data.parser, {
                    requiredProperty: data.requiredProperty,
                });
                data.alias = data.cssData.flatMap((x) => x.names);
            }
            this.computedFonts = true;
        }
    },
};
