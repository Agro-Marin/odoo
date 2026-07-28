// @ts-check

import { beforeEach, describe, expect, test } from "@odoo/hoot";
import { mockFetch } from "@odoo/hoot-mock";
import {
    clearSourceMapCache,
    decodeMappings,
    mapFramesToSource,
    parseStackFrames,
} from "@web/core/errors/stack_frames";

describe.current.tags("headless");

beforeEach(() => clearSourceMapCache());

const FIXTURE_MAP = {
    version: 3,
    sources: ["src_a.js", "entry.js"],
    mappings: "AAAO,SAASA,GAAO,CACnB,MAAM,IAAI,MAAM,MAAM,CAC1B,CCDAC,EAAK",
    names: ["boom", "boom"],
};

test("parses V8 stack format", () => {
    const stack = [
        `Error: boom`,
        `    at boom (https://example.com/web/assets/1/web.assets_web.esm.js:10:20)`,
        `    at async loadData (https://example.com/app.js:3:4)`,
        `    at https://example.com/app.js:5:6`,
        `    at <anonymous> ([native code])`,
    ].join("\n");
    expect(parseStackFrames(stack)).toEqual([
        {
            functionName: "boom",
            fileName: "https://example.com/web/assets/1/web.assets_web.esm.js",
            lineNumber: 10,
            columnNumber: 20,
        },
        {
            functionName: "async loadData",
            fileName: "https://example.com/app.js",
            lineNumber: 3,
            columnNumber: 4,
        },
        {
            functionName: "<anonymous>",
            fileName: "https://example.com/app.js",
            lineNumber: 5,
            columnNumber: 6,
        },
    ]);
});

test("parses Firefox/Safari stack format", () => {
    const stack = [
        `boom@https://example.com/bundle.js:1:38`,
        `@https://example.com/bundle.js:2:1`,
    ].join("\n");
    expect(parseStackFrames(stack)).toEqual([
        {
            functionName: "boom",
            fileName: "https://example.com/bundle.js",
            lineNumber: 1,
            columnNumber: 38,
        },
        {
            functionName: "<anonymous>",
            fileName: "https://example.com/bundle.js",
            lineNumber: 2,
            columnNumber: 1,
        },
    ]);
});

test("decodes esbuild VLQ mappings", () => {
    const lines = decodeMappings(FIXTURE_MAP.mappings);
    expect(lines).toHaveLength(1);
    expect(lines[0][0]).toEqual([0, 0, 0, 7]);
    expect(lines[0][3]).toEqual([13, 0, 1, 4]);
    expect(lines[0].at(-2)).toEqual([37, 1, 1, 0]);
});

test("maps frames through a linked sourcemap", async () => {
    const scriptUrl = "/web/assets/esm/abc123/web.assets_web.esm.js";
    mockFetch(async (input) => {
        if (String(input) === scriptUrl) {
            return new Response(
                `function o(){throw new Error("boom")}o();\n//# sourceMappingURL=web.assets_web.esm.js.map`,
            );
        }
        if (String(input).endsWith("web.assets_web.esm.js.map")) {
            return new Response(JSON.stringify(FIXTURE_MAP));
        }
        throw new Error(`unexpected fetch: ${input}`);
    });
    const mapped = await mapFramesToSource([
        {
            functionName: "o",
            fileName: scriptUrl,
            lineNumber: 1,
            columnNumber: 14,
        },
        {
            functionName: "<anonymous>",
            fileName: scriptUrl,
            lineNumber: 1,
            columnNumber: 38,
        },
    ]);
    expect(mapped).toEqual([
        {
            functionName: "o",
            fileName: "src_a.js",
            lineNumber: 2,
            columnNumber: 5,
        },
        {
            functionName: "<anonymous>",
            fileName: "entry.js",
            lineNumber: 2,
            columnNumber: 1,
        },
    ]);
});

test("maps frames through an inline data: sourcemap longer than 1KB", async () => {
    const scriptUrl = "/web/assets/esm/def456/web.assets_web.esm.js";
    const paddedMap = { ...FIXTURE_MAP, x_padding: "p".repeat(2000) };
    const dataUri = `data:application/json;base64,${btoa(JSON.stringify(paddedMap))}`;
    expect(dataUri.length).toBeGreaterThan(1024);
    mockFetch(async (input) => {
        if (String(input) === scriptUrl) {
            return new Response(
                `function o(){throw new Error("boom")}o();\n//# sourceMappingURL=${dataUri}`,
            );
        }
        if (String(input).startsWith("data:application/json;base64,")) {
            return new Response(atob(String(input).split(",")[1]));
        }
        throw new Error(`unexpected fetch: ${input}`);
    });
    const mapped = await mapFramesToSource([
        {
            functionName: "o",
            fileName: scriptUrl,
            lineNumber: 1,
            columnNumber: 14,
        },
    ]);
    expect(mapped).toEqual([
        {
            functionName: "o",
            fileName: "src_a.js",
            lineNumber: 2,
            columnNumber: 5,
        },
    ]);
});

test("frames pass through unchanged when the script has no sourcemap", async () => {
    mockFetch(async () => new Response(`function o(){}o();`));
    const frame = {
        functionName: "o",
        fileName: "/web/assets/esm/abc123/web.assets_web.esm.js",
        lineNumber: 1,
        columnNumber: 14,
    };
    expect(await mapFramesToSource([frame])).toEqual([frame]);
});

test("frames pass through unchanged when the map fetch fails", async () => {
    mockFetch(() => {
        throw new Error("network down");
    });
    const frame = {
        functionName: "o",
        fileName: "/web/assets/esm/abc123/web.assets_web.esm.js",
        lineNumber: 1,
        columnNumber: 14,
    };
    expect(await mapFramesToSource([frame])).toEqual([frame]);
});

test("non-fetchable frame origins are skipped without a fetch", async () => {
    mockFetch(() => {
        throw new Error("must not fetch");
    });
    const frames = [
        {
            functionName: "f",
            fileName: "<anonymous>",
            lineNumber: 1,
            columnNumber: 1,
        },
        {
            functionName: "g",
            fileName: "data:text/javascript,export%20default%201",
            lineNumber: 1,
            columnNumber: 1,
        },
    ];
    expect(await mapFramesToSource(frames)).toEqual(frames);
});
