// @ts-check

/**
 * ``RelationalModel._getPropertyDefinition`` registers the synthetic field for
 * a ``properties_field.property_name`` group-by axis.
 *
 * The interesting cases are the degraded ones. A property deleted from its
 * definition record still answers the read_group — its stored values are still
 * on the rows — but ``get_property_definition`` returns an EMPTY definition,
 * and a model overriding that method may return nothing at all. Neither may
 * clear ``config.groupBy``: the read_group has already run on that axis and
 * every consumer downstream dereferences ``groupBy`` as an array, so the old
 * ``config.groupBy = null`` turned a missing label into a TypeError one
 * statement later (``postprocessReadGroup`` does ``currentConfig.groupBy
 * .slice(1)`` immediately after awaiting this).
 */

import { describe, expect, test } from "@odoo/hoot";
import { RelationalModel } from "@web/model/relational_model/relational_model";

describe.current.tags("headless");

/**
 * @param {any} definitionResponse what ``get_property_definition`` answers
 */
async function resolve(definitionResponse) {
    const config = {
        resModel: "res.partner",
        context: {},
        groupBy: ["props.my_prop"],
        fields: {},
    };
    const model = {
        orm: { call: async () => definitionResponse },
    };
    await RelationalModel.prototype._getPropertyDefinition.call(
        model,
        /** @type {any} */ (config),
        "props.my_prop",
    );
    return config;
}

describe("_getPropertyDefinition", () => {
    test("a resolvable property becomes a fully typed field", async () => {
        const config = await resolve({
            name: "my_prop",
            type: "many2one",
            comodel: "res.users",
        });

        const field = config.fields["props.my_prop"];
        expect(field.name).toBe("props.my_prop");
        expect(field.propertyName).toBe("my_prop");
        expect(field.type).toBe("many2one");
        expect(field.relation).toBe("res.users");
        expect(field.relatedPropertyField).toEqual({ fieldName: "props" });
    });

    test("a deleted property keeps the axis and gets a typed placeholder", async () => {
        // what the stock server returns once the definition is gone
        const config = await resolve({});

        expect(config.groupBy).toEqual(["props.my_prop"]);
        expect(config.fields["props.my_prop"].type).toBe("char");
        expect(config.fields["props.my_prop"].name).toBe("props.my_prop");
    });

    test("an empty response keeps the axis instead of nulling it", async () => {
        // an overriding get_property_definition answering with nothing: the old
        // code set config.groupBy = null here, crashing the caller
        const config = await resolve(false);

        expect(config.groupBy).toEqual(["props.my_prop"]);
        expect(config.fields["props.my_prop"].type).toBe("char");
    });
});
