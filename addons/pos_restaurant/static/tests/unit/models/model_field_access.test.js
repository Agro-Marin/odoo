import { expect, test } from "@odoo/hoot";
import { setupPosEnv } from "@point_of_sale/../tests/unit/utils";
import { definePosRestaurantModels } from "@pos_restaurant/../tests/unit/data/generate_model_definitions";
import { pick } from "@web/core/utils/collections/objects";

definePosRestaurantModels();

/**
 * A record's fields are enumerable accessors on the MODEL CLASS PROTOTYPE, not
 * own properties of the instance -- `related_models/model_classes.js` installs
 * them with `Object.defineProperty(ModelRecordClass.prototype, ...)`. Anything
 * in core that reads a field by name has to walk the prototype chain, and
 * `pick` is the one that does: `floor_screen` uses it to write table geometry
 * back to the server. This pins that contract from the POS side, because the
 * obvious "hardening" of `pick` -- `Object.hasOwn` -- would silently make it
 * return `{}` here and the floor editor would stop saving positions.
 */
test("a table's fields survive pick(), which must not use Object.hasOwn", async () => {
    const store = await setupPosEnv();
    const table = store.models["restaurant.table"].getFirst();

    // The shape the guard in `pick` exists for: the field is NOT an own
    // property of the record, it is an enumerable accessor on the model class
    // prototype (related_models/model_classes.js).
    expect(Object.hasOwn(table, "position_h")).toBe(false);
    expect("position_h" in table).toBe(true);
    expect(typeof table.position_h).toBe("number");

    // ...and this is the call floor_screen makes when writing table geometry
    // back to the server (floor_screen.js:151 and :355).
    const geometry = pick(table, "position_h", "position_v", "width", "height");
    expect(Object.keys(geometry).sort()).toEqual([
        "height",
        "position_h",
        "position_v",
        "width",
    ]);
    expect(geometry.position_h).toBe(table.position_h);
    expect(geometry.position_v).toBe(table.position_v);

    // What the fix keeps out: members that live ONLY on Object.prototype.
    expect(pick(table, "toString", "valueOf", "hasOwnProperty")).toEqual({});

    // What it does not, and why. `constructor` is an own property of every
    // class prototype, so the walk finds it below Object.prototype. Harmless
    // here -- `model_classes.js` throws if a field name collides with an
    // existing prototype property, so `constructor` can never BE a field --
    // but worth stating rather than assuming.
    expect(Object.keys(pick(table, "constructor"))).toEqual(["constructor"]);
    expect(Object.hasOwn(Object.getPrototypeOf(table), "constructor")).toBe(true);
});
