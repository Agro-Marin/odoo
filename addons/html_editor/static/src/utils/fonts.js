/** @odoo-module native */
export const fonts = {
    /**
     * Retrieves all the CSS rules which match the given parser (Regex).
     *
     * @param {Regex} filter
     * @param {Regex} [cssFilter] Only keep rules whose cssText matches this
     * @returns {Object[]} Array of CSS rules descriptions (objects). A rule is
     *          defined by 3 values: 'selector', 'css' and 'names'. 'selector'
     *          is a string which contains the whole selector, 'css' is a string
     *          which contains the css properties and 'names' is an array of the
     *          first captured groups for each selector part. E.g.: if the
     *          filter is set to match .fa-* rules and capture the icon names,
     *          the rule:
     *              '.fa-alias1::before, .fa-alias2::before { hello: world; }'
     *          will be retrieved as
     *              {
     *                  selector: '.fa-alias1::before, .fa-alias2::before',
     *                  css: 'hello: world;',
     *                  names: ['.fa-alias1', '.fa-alias2'],
     *              }
     */
    cacheCssSelectors: {},
    getCssSelectors: function (filter, cssFilter) {
        const cacheKey = `${filter}${cssFilter || ""}`;
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
                if (cssFilter && !cssFilter.test(rules[r].cssText)) {
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
                            css: rules[r].cssText.replace(
                                /(^.*\{\s*)|(\s*\}\s*$)/g,
                                "",
                            ),
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
     * - base: class who appear on all fonts
     * - parser: regular expression used to select all font in css stylesheets
     *
     * @type Array
     */
    fontIcons: [
        { base: "fa-solid", parser: /\.(fa-(?:\w|-)+)$/i, cssFilter: /--fa\s*:/ },
    ],
    computedFonts: false,
    /**
     * Searches the fonts described by the @see fontIcons variable.
     */
    computeFonts: function () {
        if (!this.computedFonts) {
            const self = this;
            this.fontIcons.forEach((data) => {
                data.cssData = self.getCssSelectors(data.parser, data.cssFilter);
                data.alias = data.cssData.map((x) => x.names).flat();
            });
            this.computedFonts = true;
        }
    },
};
