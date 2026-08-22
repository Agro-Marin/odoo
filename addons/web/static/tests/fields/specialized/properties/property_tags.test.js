// @ts-check

import { expect, test } from "@odoo/hoot";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { PropertyTags } from "@web/fields/specialized/properties/property_tags";

test("property tag id replaces every space, not just the first", async () => {
    let definitionTags;
    const component = await mountWithCleanup(PropertyTags, {
        props: {
            selectedTags: [],
            tags: [],
            deleteAction: "tags",
            canChangeTags: true,
            onValueChange: () => {},
            onTagsChange: (/** @type {any} */ updatedTags) => {
                definitionTags = updatedTags;
            },
        },
    });

    await component.onTagCreate("New York City");
    const [id, label] = /** @type {[string, string]} */ (
        /** @type {any[]} */ (definitionTags).at(-1)
    );
    expect(id).toBe("new_york_city");
    expect(label).toBe("New York City");
});

test("a tag that cannot be deleted omits onDelete rather than passing false", async () => {
    const component = await mountWithCleanup(PropertyTags, {
        props: {
            selectedTags: ["a"],
            tags: [["a", "A", 1]],
            readonly: true,
            deleteAction: "tags",
            canChangeTags: false,
            onValueChange: () => {},
            onTagsChange: () => {},
        },
    });

    const [tag] = /** @type {any} */ (component).tagListItems;
    expect(tag.onDelete).toBe(undefined, {
        message: "false would fail TagsList's `type: Function` validation",
    });
    expect(tag.id).toBe("a");
});

test("a deletable tag still gets a callable onDelete", async () => {
    const component = await mountWithCleanup(PropertyTags, {
        props: {
            selectedTags: ["a"],
            tags: [["a", "A", 1]],
            deleteAction: "value",
            canChangeTags: true,
            onValueChange: () => {},
            onTagsChange: () => {},
        },
    });

    const [tag] = /** @type {any} */ (component).tagListItems;
    expect(typeof tag.onDelete).toBe("function");
});
