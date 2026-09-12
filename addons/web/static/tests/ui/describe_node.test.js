// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { describeNode } from "@web/ui/describe_node";

describe.current.tags("headless");

test("describeNode names a node the way a selector would", () => {
    expect(describeNode(document)).toBe("document");
    expect(describeNode(null)).toBe("null");
    expect(describeNode(undefined)).toBe("undefined");

    const el = document.createElement("div");
    expect(describeNode(el)).toBe("div");
    el.id = "root";
    el.className = "o_a o_b";
    expect(describeNode(el)).toBe("div#root.o_a.o_b");

    expect(describeNode(document.createTextNode("x"))).toBe("#text");
});
