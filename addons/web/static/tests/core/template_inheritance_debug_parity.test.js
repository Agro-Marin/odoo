// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { serverState } from "@web/../tests/web_test_helpers";
import { applyInheritance } from "@web/core/template_inheritance";

describe.current.tags("headless");

const parser = new DOMParser();
const serializer = new XMLSerializer();

/**
 * @param {string} arch
 * @param {string} inherits
 * @returns {string}
 */
function apply(arch, inherits) {
    const archDoc = parser.parseFromString(arch, "text/xml");
    const inheritsDoc = parser.parseFromString(inherits, "text/xml");
    archDoc.documentElement.setAttribute("t-translation-context", "from_target");
    return serializer.serializeToString(
        applyInheritance(
            archDoc.documentElement,
            inheritsDoc.documentElement,
            "test/from_op",
        ),
    );
}

/**
 * Debug mode must annotate the result, never alter it.
 *
 * `applyOperations` prepends a provenance comment *into the operation
 * element*, and `getNodes` copies every child of that element into the output.
 * The comment is a non-text node, which is exactly what `addBefore` keys its
 * whitespace trimming off -- so the annotation is one predicate away from
 * changing the markup. It does not today, including for a text-only operation,
 * where the comment is the only non-text node in the insertion; this pins that.
 *
 * @param {string} arch
 * @param {string} inherits
 */
function withAndWithoutDebug(arch, inherits) {
    serverState.debug = "";
    const plain = apply(arch, inherits);
    serverState.debug = "1";
    const annotated = apply(arch, inherits).replace(/<!--[\s\S]*?-->/g, "");
    return { plain, annotated };
}

test("`before` produces the same markup in debug mode", () => {
    const arch = `<t t-name="web.A"><div><span class="a"/>
        <span class="b"/>
    </div></t>`;
    const inherits = `<t t-inherit="web.A"><xpath expr="//span[@class='b']" position="before"><p class="new"/></xpath></t>`;
    const { plain, annotated } = withAndWithoutDebug(arch, inherits);
    expect(annotated).toBe(plain);
});

test("`after` produces the same markup in debug mode", () => {
    const arch = `<t t-name="web.A"><div><span class="a"/>
        <span class="b"/>
    </div></t>`;
    const inherits = `<t t-inherit="web.A"><xpath expr="//span[@class='a']" position="after"><p class="new"/></xpath></t>`;
    const { plain, annotated } = withAndWithoutDebug(arch, inherits);
    expect(annotated).toBe(plain);
});

test("`inside` produces the same markup in debug mode", () => {
    const arch = `<t t-name="web.A"><div>
        <span class="a"/>
    </div></t>`;
    const inherits = `<t t-inherit="web.A"><xpath expr="//div" position="inside"><p class="new"/></xpath></t>`;
    const { plain, annotated } = withAndWithoutDebug(arch, inherits);
    expect(annotated).toBe(plain);
});

test("`replace` produces the same markup in debug mode", () => {
    const arch = `<t t-name="web.A"><div><span class="a"/>
        <span class="b"/>
    </div></t>`;
    const inherits = `<t t-inherit="web.A"><xpath expr="//span[@class='b']" position="replace"><p class="new"/></xpath></t>`;
    const { plain, annotated } = withAndWithoutDebug(arch, inherits);
    expect(annotated).toBe(plain);
});

test("a text-only operation produces the same markup in debug mode", () => {
    // `addBefore` trims the preceding text node only when at least one
    // inserted node is not text. A text-only operation is the shape where the
    // provenance comment could flip that predicate.
    const arch = `<t t-name="web.A"><div><span class="a"/>
        <span class="b"/>
    </div></t>`;
    const inherits = `<t t-inherit="web.A"><xpath expr="//span[@class='b']" position="before">just text</xpath></t>`;
    const { plain, annotated } = withAndWithoutDebug(arch, inherits);
    expect(annotated).toBe(plain);
});
