// @ts-check

/**
 * Pins the sample-data ORM swap in ``useModelWithSampleData``: when the
 * sample-mode load throws (e.g. SampleServer.UnimplementedRouteError from a
 * non-mocked route), ``model.orm`` must be restored to the real ORM — a
 * leaked sample ORM routes every subsequent user action to the in-memory
 * fake for the rest of the session.
 */

import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-mock";
import { Component, xml } from "@odoo/owl";
import { mountWithCleanup } from "@web/../tests/web_test_helpers";
import { Model, useModelWithSampleData } from "@web/model/model";

test("model.orm is restored when the sample-data load throws", async () => {
    expect.errors(1);
    let model = null;
    let realOrm = null;

    class BoomModel extends Model {
        async load() {
            if (realOrm && this.orm !== realOrm) {
                // Second load — running against the sample ORM.
                throw new Error("sample boom");
            }
        }

        hasData() {
            return false;
        }
    }

    class Parent extends Component {
        static template = xml`<div class="parent"/>`;
        static props = ["*"];
        setup() {
            model = useModelWithSampleData(BoomModel, {}, { lazy: true });
            realOrm = model.orm;
        }
    }

    await mountWithCleanup(Parent, {
        props: { useSampleModel: true, resModel: "res.partner", fields: {} },
    });
    await animationFrame();

    expect.verifyErrors([/sample boom/]);
    // The real ORM was restored despite the throw; sample mode is off.
    expect(model.orm).toBe(realOrm);
    expect(model.useSampleModel).toBe(false);
});
