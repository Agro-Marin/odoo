import { registry } from "@web/core/registry";

// Typing searches on every keystroke, so a partial query can leave an older, truncated list
// on screen. A list in which every tax matches the full prefix is complete: only two taxes match.
const TAX_ITEM = ".o-autocomplete--dropdown-item:not(.o_m2o_dropdown_option)";
const COMPLETE_MENU = `.o-autocomplete--dropdown-menu:has(${TAX_ITEM}):not(:has(${TAX_ITEM}:not(:contains(TAXPICK))))`;

function taxPickerSteps(offered, hidden) {
    return [
        {
            content: "Open the taxes of the first line",
            trigger:
                ".o_field_one2many[name=line_ids] .o_data_row:first td[name=tax_ids]",
            run: "click",
        },
        {
            trigger:
                ".o_data_row.o_selected_row td[name=tax_ids] .o-autocomplete--input",
            run: "edit TAXPICK",
        },
        {
            content: "Wait for the search of the full prefix",
            trigger: COMPLETE_MENU,
        },
        {
            content: `The picker offers ${offered}`,
            trigger: `${COMPLETE_MENU} ${TAX_ITEM}:contains(${offered})`,
        },
        {
            content: `The picker does not offer ${hidden}`,
            trigger: `${COMPLETE_MENU}:not(:has(${TAX_ITEM}:contains(${hidden})))`,
        },
    ];
}

registry
    .category("web_tour.tours")
    .add("purchase_order_line_tax_picker_foreign_vat", {
        steps: () => taxPickerSteps("TAXPICK DE", "TAXPICK HOME"),
    })
    .add("purchase_order_line_tax_picker_domestic", {
        steps: () => taxPickerSteps("TAXPICK HOME", "TAXPICK DE"),
    });
