// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { patchWithCleanup } from "@web/../tests/web_test_helpers";
import Class from "@web/legacy/js/core/class";

// Hoot port of the former QUnit suite `tests/legacy/legacy_tests/core/class_tests.js`.
// `Class` (src/legacy/js/core/class.js) is still production code: it is the
// base of `publicWidget.Widget` shipped in `web.assets_frontend`.

describe.current.tags("headless");

test("basic class creation", () => {
    const C = Class.extend({
        foo() {
            return this.somevar;
        },
    });
    const i = new C();
    i.somevar = 3;

    expect(i).toBeInstanceOf(C);
    expect(i.foo()).toBe(3);
});

test("class initialization", () => {
    const C1 = Class.extend({
        init() {
            this.foo = 3;
        },
    });
    const C2 = Class.extend({
        init(arg) {
            this.foo = arg;
        },
    });

    const i1 = new C1();
    const i2 = new C2(42);

    expect(i1.foo).toBe(3);
    expect(i2.foo).toBe(42);
});

test("inheritance", () => {
    const C0 = Class.extend({
        foo() {
            return 1;
        },
    });
    const C1 = C0.extend({
        foo() {
            return 1 + this._super();
        },
    });
    const C2 = C1.extend({
        foo() {
            return 1 + this._super();
        },
    });

    expect(new C0().foo()).toBe(1);
    expect(new C1().foo()).toBe(2);
    expect(new C2().foo()).toBe(3);
});

test("in-place extension", () => {
    const C0 = Class.extend({
        foo() {
            return 3;
        },
        qux() {
            return 3;
        },
        bar: 3,
    });

    C0.include({
        foo() {
            return 5;
        },
        qux() {
            return 2 + this._super();
        },
        bar: 5,
        baz: 5,
    });

    expect(new C0().bar).toBe(5);
    expect(new C0().baz).toBe(5);
    expect(new C0().foo()).toBe(5);
    expect(new C0().qux()).toBe(5);
});

test("in-place extension and inheritance", () => {
    const C0 = Class.extend({
        foo() {
            return 1;
        },
        bar() {
            return 1;
        },
    });
    const C1 = C0.extend({
        foo() {
            return 1 + this._super();
        },
    });
    expect(new C1().foo()).toBe(2);
    expect(new C1().bar()).toBe(1);

    C1.include({
        foo() {
            return 2 + this._super();
        },
        bar() {
            return 1 + this._super();
        },
    });
    expect(new C1().foo()).toBe(4);
    expect(new C1().bar()).toBe(2);
});

test("in-place extensions alter existing instances", () => {
    const C0 = Class.extend({
        foo() {
            return 1;
        },
        bar() {
            return 1;
        },
    });
    const i = new C0();
    expect(i.foo()).toBe(1);
    expect(i.bar()).toBe(1);

    C0.include({
        foo() {
            return 2;
        },
        bar() {
            return 2 + this._super();
        },
    });
    expect(i.foo()).toBe(2);
    expect(i.bar()).toBe(3);
});

test("include: new method mentioning _super is installed, not dropped", () => {
    patchWithCleanup(console, { warn: () => expect.step("warn") });
    const C0 = Class.extend({});

    C0.include({
        foo() {
            // an innocuous _super mention in a comment must not drop the method
            return 42;
        },
    });

    expect.verifySteps(["warn"]);
    expect(new C0().foo()).toBe(42);
});

test("include: new method actually calling _super throws loudly", () => {
    patchWithCleanup(console, { warn: () => expect.step("warn") });
    const C0 = Class.extend({});

    C0.include({
        bar() {
            return this._super();
        },
    });

    expect.verifySteps(["warn"]);
    expect(() => new C0().bar()).toThrow(/no _super implementation/);
});

test("in-place extension of subclassed types", () => {
    const C0 = Class.extend({
        foo() {
            return 1;
        },
        bar() {
            return 1;
        },
    });
    const C1 = C0.extend({
        foo() {
            return 1 + this._super();
        },
        bar() {
            return 1 + this._super();
        },
    });
    const i = new C1();

    expect(i.foo()).toBe(2);

    C0.include({
        foo() {
            return 2;
        },
        bar() {
            return 2 + this._super();
        },
    });

    expect(i.foo()).toBe(3);
    expect(i.bar()).toBe(4);
});
