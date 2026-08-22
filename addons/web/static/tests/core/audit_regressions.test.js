// @ts-check

import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import { Domain } from "@web/core/domain";
import { formatFieldFloat } from "@web/core/formatters";
import { localization } from "@web/core/l10n/localization";
import { RPCCache } from "@web/core/network/rpc_cache";
import { TemplateRegistry } from "@web/core/templates";
import { getDefaultPath } from "@web/core/tree/utils";
import { formatFloat } from "@web/core/utils/format/numbers";

describe.current.tags("headless");

describe("templates: every derived form is invalidated together", () => {
    test("a processor registered after a template was parsed still reaches it", () => {
        const reg = new TemplateRegistry();
        reg.registerTemplate(
            "probe.A",
            "/web/static/x.xml",
            `<t t-name="probe.A"><img src="real.png"/></t>`,
        );
        expect(
            reg.getTemplate("probe.A").querySelector("img").getAttribute("src"),
        ).toBe("real.png");
        reg.registerTemplateProcessor((doc) => {
            for (const img of doc.querySelectorAll("img[src]")) {
                img.setAttribute("src", "MOCKED");
            }
        });
        expect(
            reg.getTemplate("probe.A").querySelector("img").getAttribute("src"),
        ).toBe("MOCKED");
    });

    test("setUrlFilters invalidates templates compiled under the old filters", () => {
        const reg = new TemplateRegistry();
        reg.registerTemplate(
            "probe.B",
            "/web/static/b.xml",
            `<t t-name="probe.B"><div class="base"/></t>`,
        );
        reg.registerTemplateExtension(
            "probe.B",
            "/other/static/ext.xml",
            `<t t-inherit="probe.B"><xpath expr="//div" position="after"><span class="ext"/></xpath></t>`,
        );
        expect(reg.getTemplate("probe.B").querySelector(".ext")).not.toBe(null);

        const restore = reg.setUrlFilters([(url) => !url.startsWith("/other")]);
        expect(reg.getTemplate("probe.B").querySelector(".ext")).toBe(null);

        restore();
        expect(reg.getTemplate("probe.B").querySelector(".ext")).not.toBe(null);
    });

    test("a refused duplicate registration does not claim the key", () => {
        const reg = new TemplateRegistry();
        reg.registerTemplate("probe.C", "/a.xml", `<t t-name="probe.C"/>`);
        expect(() =>
            reg.registerTemplate("probe.C", "/b.xml", `<t t-name="probe.C"><i/></t>`),
        ).toThrow();
        expect(reg.registered.size).toBe(1);
    });
});

describe("Domain: the compiled predicate follows the ast", () => {
    test("reassigning ast does not serve the previous predicate", () => {
        const d = new Domain([["a", "=", 1]]);
        expect(d.contains({ a: 1 })).toBe(true);
        d.ast = new Domain([["a", "=", 2]]).ast;
        expect(d.toString()).toBe(`[("a", "=", 2)]`);
        expect(d.contains({ a: 1 })).toBe(false);
        expect(d.contains({ a: 2 })).toBe(true);
    });

    test("two domains sharing one ast share one compilation", () => {
        const a = new Domain([["x", "=", 1]]);
        const b = Domain.fromASTValue(a.ast.value);
        expect(a.contains({ x: 1 })).toBe(true);
        expect(b.contains({ x: 1 })).toBe(true);
    });
});

describe("getDefaultPath returns a key of fieldDefs", () => {
    test("works when the field definition carries no redundant `name`", () => {
        const fieldDefs = { user_id: { type: "many2one", relation: "res.users" } };
        const path = getDefaultPath(fieldDefs);
        expect(path).toBe("user_id");
        expect(fieldDefs[path]).not.toBe(undefined);
    });

    test("falls back to the first key when no special field is present", () => {
        const fieldDefs = { some_field: { type: "char" } };
        expect(getDefaultPath(fieldDefs)).toBe("some_field");
    });
});

describe("RPCCache", () => {
    test("a malformed disk secret is refused rather than silently truncated", () => {
        expect(() => new RPCCache("probe_odd", 1, "abc")).toThrow();
        expect(() => new RPCCache("probe_nonhex", 1, "zzzz")).toThrow();
        expect(() => new RPCCache("probe_none", 1, null)).not.toThrow();
        expect(() => new RPCCache("probe_ok", 1, "00ff10")).not.toThrow();
    });

    test("invalidating a table leaves an in-flight request of another table alone", async () => {
        const cache = new RPCCache("probe_prefix", 1, null);
        const { promise: a, resolve: resolveA } = Promise.withResolvers();
        const { promise: b, resolve: resolveB } = Promise.withResolvers();
        const pa = cache.read("/web", "k", () => a, {});
        const pb = cache.read("/web/dataset/call_kw", "k", () => b, {});

        cache.invalidate("/web");
        expect(Object.keys(cache.pendingRequests)).toEqual(["/web/dataset/call_kw/k"]);

        resolveA("A");
        resolveB("B");
        await Promise.all([pa, pb]);
    });

    test("read announces synchronously that it is issuing a request", () => {
        const cache = new RPCCache("probe_issued", 1, null);
        const steps = [];
        cache.read("t", "k", () => Promise.resolve(1), {
            onRequestIssued: () => steps.push("issued"),
        });
        expect(steps).toEqual(["issued"]);
    });
});

describe("format function names say which layer they belong to", () => {
    beforeEach(() => {
        patchWithCleanup(localization, {
            decimalPoint: ".",
            thousandsSep: ",",
            grouping: [3, 0],
            code: "en_US",
        });
    });

    test("the field layer and the primitive layer are distinguishable", () => {
        expect(formatFieldFloat(NaN)).toBe("");
        expect(formatFloat(NaN)).toBe("NaN");
    });
});
