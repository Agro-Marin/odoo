// @ts-check

/**
 * AUDIT CHALLENGE — `<label for="X"/>` placed AFTER `<field id="X">`.
 *
 * `compileField` READS the pending-label bucket keyed by `id || name`
 * (form_compiler.js), but REGISTERS the forward-reference callback keyed by
 * `name` only. So when a label referencing the field's `id` is compiled after
 * the field, the lookup misses, the label is pushed into a bucket nobody will
 * ever drain, and it renders as a bare <label> — no text, no field binding.
 *
 * The reverse order works, which is why every existing test passes.
 */

import { describe, expect, test } from "@odoo/hoot";
import { FormCompiler } from "@web/views/form/form_compiler";

describe.current.tags("headless");

function compileTemplate(arch) {
    const parser = new DOMParser();
    const xml = parser.parseFromString(arch, "text/xml");
    const compiler = new FormCompiler({ form: xml.documentElement });
    return compiler.compile("form", {});
}

describe("label/field association by id", () => {
    test("label BEFORE field, for= matches id (control)", () => {
        const arch = /*xml*/ `<form>
            <label for="float_field2"/>
            <field field_id="float_field" name="float_field" id="float_field2"/>
        </form>`;
        expect(compileTemplate(arch).outerHTML).toInclude("FormLabel");
    });

    test("label BEFORE field, for= matches name (control)", () => {
        const arch = /*xml*/ `<form>
            <label for="float_field"/>
            <field field_id="float_field" name="float_field"/>
        </form>`;
        expect(compileTemplate(arch).outerHTML).toInclude("FormLabel");
    });

    test("label AFTER field, for= matches name (control)", () => {
        const arch = /*xml*/ `<form>
            <field field_id="float_field" name="float_field"/>
            <label for="float_field"/>
        </form>`;
        expect(compileTemplate(arch).outerHTML).toInclude("FormLabel");
    });

    test("label AFTER field, for= matches id", () => {
        const arch = /*xml*/ `<form>
            <field field_id="float_field" name="float_field" id="float_field2"/>
            <label for="float_field2"/>
        </form>`;
        // Currently emits a bare <label/> instead of a <FormLabel/>.
        expect(compileTemplate(arch).outerHTML).toInclude("FormLabel");
    });
});
