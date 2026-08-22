// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import {
    fullAnnotatedTraceback,
    fullTraceback,
    getErrorTechnicalName,
} from "@web/core/errors/error_utils";

describe.current.tags("headless");

/**
 * @param {string} message
 * @param {unknown} [cause]
 */
function makeError(message, cause) {
    const error = new Error(message, cause !== undefined ? { cause } : undefined);
    error.stack = `Error: ${message}\n    at doThing (some_module.js:12:34)`;
    return error;
}

describe("fullTraceback", () => {
    test("walks the cause chain", () => {
        const root = makeError("root");
        const middle = makeError("middle", root);
        const top = makeError("top", middle);
        const traceback = fullTraceback(top);
        expect(traceback).toInclude("top");
        expect(traceback).toInclude("Caused by:");
        expect(traceback).toInclude("middle");
        expect(traceback).toInclude("root");
    });

    test("a non-Error cause is stringified rather than formatted", () => {
        expect(fullTraceback(makeError("top", "just a string"))).toInclude(
            "Caused by: just a string",
        );
    });

    test("a cyclic cause chain terminates", () => {
        const a = makeError("a");
        const b = makeError("b", a);
        /** @type {any} */ (a).cause = b;
        const traceback = fullTraceback(a);
        expect(traceback).toInclude("a");
        expect(traceback).toInclude("b");
        expect(traceback.match(/Caused by:/g)?.length).toBe(1);
    });
});

describe("fullAnnotatedTraceback", () => {
    test("returns the traceback when the error carries no errorEvent", async () => {
        const error = makeError("plain");
        const traceback = await fullAnnotatedTraceback(error);
        expect(typeof traceback).toBe("string");
        expect(traceback).toInclude("plain");
        expect(/** @type {any} */ (error).annotatedTraceback).toBe(traceback);
    });

    test("throws the same error the first time, after caching the annotation", async () => {
        const error = makeError("with event");
        let prevented = 0;
        /** @type {any} */ (error).errorEvent = {
            preventDefault() {
                prevented++;
            },
        };

        let thrown;
        try {
            await fullAnnotatedTraceback(error);
        } catch (e) {
            thrown = e;
        }
        expect(thrown).toBe(error, { message: "rethrows the very same error object" });
        expect(prevented).toBe(1, { message: "preventDefault ran synchronously" });
        expect(typeof (/** @type {any} */ (error).annotatedTraceback)).toBe("string");
        expect(/** @type {any} */ (error).annotatedTraceback).toInclude("with event");
    });

    test("the re-entrant call returns the cached traceback instead of throwing", async () => {
        const error = makeError("second pass");
        let prevented = 0;
        /** @type {any} */ (error).errorEvent = {
            preventDefault() {
                prevented++;
            },
        };
        await fullAnnotatedTraceback(error).catch(() => {});
        const cached = /** @type {any} */ (error).annotatedTraceback;

        await expect(fullAnnotatedTraceback(error)).resolves.toBe(cached);
        expect(prevented).toBe(1);
    });
});

describe("getErrorTechnicalName", () => {
    test("prefers an explicit name over the constructor name", () => {
        class MyError extends Error {}
        expect(getErrorTechnicalName(new MyError("x"))).toBe("MyError");
        const named = new Error("x");
        named.name = "SomethingElse";
        expect(getErrorTechnicalName(named)).toBe("SomethingElse");
        expect(getErrorTechnicalName(new Error("x"))).toBe("Error");
    });
});
