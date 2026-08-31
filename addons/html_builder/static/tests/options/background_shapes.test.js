import { backgroundShapesDefinition } from "@html_builder/plugins/background_option/background_shapes_definition";
import { describe, expect, globals, test } from "@odoo/hoot";

describe.current.tags("desktop");

/**
 * The shape ids a named subgroup offers, whichever top-level group holds it.
 */
function shapeIdsOf(subgroupName) {
    for (const group of Object.values(backgroundShapesDefinition)) {
        const subgroup = group.subgroups[subgroupName];
        if (subgroup) {
            return Object.keys(subgroup.shapes);
        }
    }
    return [];
}

/**
 * A shape id is `<module>/<path>`, and the drawing behind it is
 * `/<module>/static/shapes/<path>.svg`. Ask the real server for it: a
 * definition entry with no file behind it paints nothing.
 */
async function expectShapesAreShipped(ids) {
    for (const id of ids) {
        const [module, ...path] = id.split("/");
        const response = await globals.fetch.call(
            window,
            `/${module}/static/shapes/${path.join("/")}.svg`
        );
        expect(response.ok).toBe(true, { message: `${id} is served` });
        expect(await response.text()).toInclude("<svg");
    }
}

test("the Blurry group offers 07 and 08", async () => {
    const ids = shapeIdsOf("blurry");
    expect(ids).toInclude("html_builder/Blurry/07");
    expect(ids).toInclude("html_builder/Blurry/08");
    await expectShapesAreShipped(["html_builder/Blurry/07", "html_builder/Blurry/08"]);
});
