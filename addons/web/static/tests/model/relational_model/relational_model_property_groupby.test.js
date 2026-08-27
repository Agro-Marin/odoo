// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { RelationalModel } from "@web/model/relational_model/relational_model";

describe.current.tags("headless");

/**
 * @param {any} definitionResponse
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
        expect(field.relatedPropertyField).toEqual({ name: "props" });
    });

    test("a deleted property keeps the axis and gets a typed placeholder", async () => {
        const config = await resolve({});

        expect(config.groupBy).toEqual(["props.my_prop"]);
        expect(config.fields["props.my_prop"].type).toBe("char");
        expect(config.fields["props.my_prop"].name).toBe("props.my_prop");
    });

    test("an empty response keeps the axis instead of nulling it", async () => {
        const config = await resolve(false);

        expect(config.groupBy).toEqual(["props.my_prop"]);
        expect(config.fields["props.my_prop"].type).toBe("char");
    });
});
