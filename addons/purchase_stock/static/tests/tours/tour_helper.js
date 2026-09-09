import { assert } from "@stock/../tests/tours/tour_helper";

export const catalogSuggestion = {
    /**
     * @param {string} [basedOn]
     * @param {number} [nbDays]
     * @param {number} [factor]
     */
    setParameters({ basedOn = false, nbDays = false, factor = false }) {
        const steps = [];
        if (nbDays) {
            steps.push({
                trigger: "input.o_PurchaseSuggestInput:eq(0)",
                run: `edit ${nbDays}`,
            });
        }
        if (factor) {
            steps.push({
                trigger: "input.o_PurchaseSuggestInput:eq(1)",
                run: `edit ${factor}`,
            });
        }
        if (basedOn) {
            steps.push(
                {
                    trigger:
                        ".o_TimePeriodSelectionField .o_select_menu .dropdown-toggle:visible",
                    run: "click",
                },
                {
                    trigger: ".o_select_menu_menu:visible",
                },
                {
                    trigger: `.o_select_menu_menu .o_select_menu_item:contains('${basedOn}'):visible`,
                    run: "click",
                },
            );
        }
        return steps;
    },

    /**
     * @param {string} [basedOn]
     * @param {number} [nbDays]
     * @param {number} [factor]
     */
    assertParameters({ basedOn = false, nbDays = false, factor = false }) {
        const steps = [];

        if (nbDays) {
            steps.push({
                content: "Check number days saved",
                trigger: "input.o_PurchaseSuggestInput:eq(0)",
                run() {
                    const days = parseInt(this.anchor.value, 10);
                    assert(days, nbDays, `Expected days ${nbDays}, got ${days}`);
                },
            });
        }
        if (factor) {
            steps.push({
                content: "Check percent factor saved",
                trigger: "input.o_PurchaseSuggestInput:eq(1)",
                run() {
                    const percent = parseInt(this.anchor.value, 10);
                    assert(
                        percent,
                        factor,
                        `Expected percent factor ${factor}, got ${percent}`,
                    );
                },
            });
        }
        if (basedOn) {
            steps.push({
                content: "Check based-on saved",
                trigger: ".o_TimePeriodSelectionField",
                run() {
                    const drop = this.anchor.querySelector(".o_select_menu_toggler");
                    assert(
                        drop.value,
                        basedOn,
                        `Expected based on ${basedOn}, got ${drop.value}`,
                    );
                },
            });
        }

        return steps;
    },

    /**
     * @param {string} productName
     * @param {number} [monthly]
     * @param {number} [suggest]
     * @param {number} [forecast]
     */
    assertCatalogRecord(productName, { monthly, suggest, forecast } = {}) {
        const steps = [];
        if (monthly) {
            steps.push({
                content: `Check catalog record monthly demand for product ${productName}`,
                trigger: `.o_kanban_record:contains('${productName}') span[name='kanban_monthly_demand_qty']:visible:contains('${monthly}')`,
            });
        }
        if (suggest) {
            steps.push({
                content: `Check catalog record suggested quantity for product ${productName}`,
                trigger: `.o_kanban_record:contains('${productName}') div[name='kanban_purchase_suggest'] span:visible:contains('${suggest}')`,
            });
        }
        if (forecast) {
            steps.push({
                content: `Check catalog record forecasted quantity for product ${productName}`,
                trigger: `.o_kanban_record:contains('${productName}') span[name='o_kanban_forecasted_qty']:visible:contains('${forecast}')`,
            });
        }
        return steps;
    },

    /** @param {boolean} turnOn */
    toggleSuggest(turnOn) {
        return [
            {
                trigger: 'div[name="search-suggest-toggle"] input',
                run: "click",
            },
            {
                trigger: `div[name="search-suggest-toggle"] input:${
                    turnOn ? "checked" : "not(:checked)"
                }`,
            },
        ];
    },

    /**
     * @param {string} product
     * @param {number } expectedOrder
     */
    checkKanbanRecordPosition(product, expectedOrder) {
        const trigger = `.o_purchase_product_kanban_catalog_view article.o_kanban_record:nth-child(${expectedOrder + 1}):contains("${product}")`;
        return [{ trigger }];
    },

    removeSuggestFilter() {
        const content = "Remove the Suggested filter";
        const trigger = '.o_facet_value:contains("Suggested")';
        const run = async (actions) => {
            const filters = [...document.querySelectorAll(".o_searchview_facet")];
            const suggestedFilter = filters.find((el) =>
                el.textContent.includes("Suggested"),
            );
            await actions.click(suggestedFilter.querySelector(".o_facet_remove"));
        };
        return [{ content, trigger, run }];
    },

    addAllSuggestions() {
        const content = "Add all suggestion to the PO";
        const trigger = 'button[name="suggest_add_all"]';
        return [{ content, trigger, run: "click" }];
    },
};
