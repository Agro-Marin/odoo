/** @odoo-module native */
export const fonts = {
    /**
     * @param {Regex} filter
     * @param {Regex} [cssFilter]
     * @returns {Object[]}
     */
    cacheCssSelectors: {},
    getCssSelectors: function (filter, cssFilter) {
        const cacheKey = `${filter}${cssFilter || ""}`;
        if (this.cacheCssSelectors[cacheKey]) {
            return this.cacheCssSelectors[cacheKey];
        }
        this.cacheCssSelectors[cacheKey] = [];
        // FontAwesome 7 writes an icon and each of its aliases as separate
        // rules with the same glyph, canonical name first; one icon per
        // glyph, or the picker lists it twice and stores whichever name
        // was clicked.
        const byCss = new Map();
        const sheets = document.styleSheets;
        for (let i = 0; i < sheets.length; i++) {
            let rules;
            try {
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
                    const known = byCss.get(data.css);
                    if (known) {
                        known.selector += ", " + data.selector;
                        known.names.push(...data.names);
                    } else {
                        byCss.set(data.css, data);
                        this.cacheCssSelectors[cacheKey].push(data);
                    }
                }
            }
        }
        return this.cacheCssSelectors[cacheKey];
    },
    fontIcons: [
        { base: "fa-solid", parser: /\.(fa-(?:\w|-)+)$/i, cssFilter: /--fa\s*:/ },
    ],
    computedFonts: false,
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
