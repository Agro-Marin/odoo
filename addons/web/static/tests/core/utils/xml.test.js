// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { formatXML, parseXML } from "@web/core/utils/dom/xml";

describe.current.tags("headless");

test("parse error throws an exception", () => {
    expect(() => parseXML("<invalid'>")).toThrow("error occured while parsing");
    expect(() => parseXML("<div><div>Valid</div><div><Invalid</div></div>")).toThrow(
        "error occured while parsing",
    );
});

test("formatXML does not crash on unbalanced XML", () => {
    expect(() => formatXML("<div></div></div>")).not.toThrow();
    expect(() => formatXML("</div>")).not.toThrow();
    const out = formatXML("<a><b>x</b></a>");
    expect(out).toInclude("<a>");
    expect(out).toInclude("<b>x</b>");
});
