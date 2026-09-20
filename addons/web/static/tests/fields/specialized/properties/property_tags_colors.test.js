import { expect, test } from "@odoo/hoot";
import { click, edit } from "@odoo/hoot-dom";
import { animationFrame, runAllTimers } from "@odoo/hoot-mock";
import { mountWithCleanup, patchWithCleanup } from "@web/../tests/web_test_helpers";
import { PropertyTags } from "@web/fields/specialized/properties/property_tags";

for (const [previousColor, expectedColor] of [
    [-14, -1],
    [-3, -2],
    [-2, -1],
    [-1, 1],
    [0, 1],
    [10, 11],
    [11, 1],
    [12, 1],
]) {
    test(`creating a property tag preserves the sequence after ${previousColor}`, async () => {
        await mountWithCleanup(PropertyTags, {
            props: {
                tags: [["existing", "Existing", previousColor]],
                selectedTags: [],
                canChangeTags: true,
                deleteAction: "value",
                onTagsChange(tags, selectedTags) {
                    expect(tags).toEqual([
                        ["existing", "Existing", previousColor],
                        ["new_tag", "New tag", expectedColor],
                    ]);
                    expect(selectedTags).toEqual(["new_tag"]);
                    expect.step("created");
                },
            },
        });
        await click(".o_field_property_dropdown_menu input");
        await edit("New tag");
        await runAllTimers();
        await click(".o_field_property_dropdown_add .dropdown-item");
        await animationFrame();
        expect.verifySteps(["created"]);
    });
}

for (const [random, color] of [
    [0, 1],
    [0.999999, 11],
]) {
    test(`the first property tag maps random ${random} to color ${color}`, async () => {
        patchWithCleanup(Math, { random: () => random });
        const component = await mountWithCleanup(PropertyTags, {
            props: {
                tags: [],
                selectedTags: [],
                canChangeTags: true,
                deleteAction: "value",
                onTagsChange(tags) {
                    expect(tags).toEqual([["first", "First", color]]);
                    expect.step("created");
                },
            },
        });
        await component.onTagCreate("First");
        expect.verifySteps(["created"]);
    });
}
