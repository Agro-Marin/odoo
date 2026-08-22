import { expect, test } from "@odoo/hoot";
import VariantMixin from "@website_sale/js/variant_mixin";

/**
 * Build the shape `variant_templates.xml` renders: one radio input per attribute value,
 * each carrying `js_variant_change` plus the attribute's `create_variant` as a second
 * class, and the exclusion payload on a `ul[data-attribute-exclusions]`.
 *
 * Two variant attributes, because that is the shape the archived-combination branches
 * are written for: the "off by one" branch greys a value out *because of* another
 * selected value, so it has nothing to say about a template with a single variant
 * attribute (there it skips the only member of the archived combination).
 *
 *   Size (always):                    11 Small [selected], 12 Large
 *   Colour (always):                  21 Red [selected],   22 Blue
 *   Engraving (no_variant, optional): 31 None [selected],  32 Initials
 */
function makeProductDom({ withNoVariant, archivedCombinations }) {
    const container = document.createElement("div");
    container.classList.add("js_product");
    const exclusions = {
        exclusions: {},
        parent_exclusions: {},
        archived_combinations: archivedCombinations,
        mapped_attribute_names: {
            11: "Small",
            12: "Large",
            21: "Red",
            22: "Blue",
            31: "None",
            32: "Initials",
        },
    };
    const values = [
        { id: 11, createVariant: "always", checked: true },
        { id: 12, createVariant: "always", checked: false },
        { id: 21, createVariant: "always", checked: true },
        { id: 22, createVariant: "always", checked: false },
    ];
    if (withNoVariant) {
        values.push(
            { id: 31, createVariant: "no_variant", checked: true },
            { id: 32, createVariant: "no_variant", checked: false },
        );
    }
    container.innerHTML = `
        <ul data-attribute-exclusions='${JSON.stringify(exclusions)}'>
            ${values
                .map(
                    (v) => `<li>
                        <label>
                            <input type="radio" value="${v.id}"
                                   class="js_variant_change ${v.createVariant}"
                                   ${v.checked ? "checked" : ""}/>
                        </label>
                    </li>`,
                )
                .join("")}
        </ul>`;
    document.body.appendChild(container);
    return container;
}

const isGreyedOut = (parent, ptavId) =>
    parent
        .querySelector(`input[value="${ptavId}"]`)
        .classList.contains("css_not_available");

test("archived combination greys out the completing value (variant attributes only)", () => {
    // The control: this always worked, and must keep working.
    const parent = makeProductDom({
        withNoVariant: false,
        archivedCombinations: [[12, 21]], // Large + Red is archived
    });
    VariantMixin._checkExclusions(parent, [11, 21]);
    expect(isGreyedOut(parent, 12)).toBe(true);
    expect(isGreyedOut(parent, 22)).toBe(false);
    parent.remove();
});

test("archived combination greys out the completing value with a no_variant attribute too", () => {
    // Regression, measured against a real database: `archived_combinations` holds the
    // PTAVs of archived *variants* and never a `no_variant` value, while the DOM
    // combination is every `js_variant_change` input and does. Comparing their lengths
    // made both branches unreachable, so the archived value was offered to the shopper
    // and "Add to cart" silently disabled instead (`_is_combination_possible` is false
    // server-side, so nothing worse than that could follow).
    const parent = makeProductDom({
        withNoVariant: true,
        archivedCombinations: [[12, 21]],
    });
    VariantMixin._checkExclusions(parent, [11, 21, 31]);
    expect(isGreyedOut(parent, 12)).toBe(true);
    // The no_variant values take no part in variant identity and must stay selectable.
    expect(isGreyedOut(parent, 31)).toBe(false);
    expect(isGreyedOut(parent, 32)).toBe(false);
    parent.remove();
});

test("the currently selected archived combination greys its own values out", () => {
    const parent = makeProductDom({
        withNoVariant: true,
        archivedCombinations: [[11, 21]], // exactly what is selected
    });
    VariantMixin._checkExclusions(parent, [11, 21, 31]);
    expect(isGreyedOut(parent, 11)).toBe(true);
    expect(isGreyedOut(parent, 21)).toBe(true);
    expect(isGreyedOut(parent, 31)).toBe(false);
    parent.remove();
});
