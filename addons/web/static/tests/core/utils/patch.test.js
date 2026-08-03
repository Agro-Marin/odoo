// @ts-check

import { describe, expect, test } from "@odoo/hoot";
import { patch, patchInfo } from "@web/core/utils/patch";

class BaseClass {
    static staticStr = "base";
    static staticObj = { base: "base" };
    static staticArr = ["base"];
    static staticFn() {
        expect.step("base.staticFn");
    }

    constructor() {
        this.setup();
    }
    setup() {
        this._dynamic = "base";

        this.str = "base";
        this.obj = { base: "base" };
        this.arr = ["base"];

        expect.step("base.setup");
    }
    fn() {
        expect.step("base.fn");
    }
    async asyncFn() {
        expect.step(`base.${this.str}`);
    }
    get dynamic() {
        return this._dynamic;
    }
    set dynamic(value) {
        this._dynamic = value;
    }
}

function applyGenericPatch(Klass, tag) {
    return patch(Klass.prototype, {
        setup() {
            super.setup();
            expect.step(`${tag}.setup`);
        },
        fn() {
            super.fn();
            expect.step(`${tag}.fn`);
        },
        async asyncFn() {
            await Promise.resolve();
            await super.asyncFn(...arguments);
            expect.step(`${tag}.${this.str}`);
        },
    });
}

function applyGenericStaticPatch(Klass, tag) {
    return patch(Klass, {
        staticStr: Klass.staticStr + tag,
        staticArr: [...Klass.staticArr, tag],
        staticObj: { ...Klass.staticObj, patch: tag },
        staticFn() {
            super.staticFn();
            expect.step(`${tag}.staticFn`);
        },
    });
}

function createGenericExtension() {
    return class Extension extends BaseClass {
        static staticStr = BaseClass.staticStr + "extension";
        static staticArr = [...BaseClass.staticArr, "extension"];
        static staticObj = { ...BaseClass.staticObj, extension: "extension" };
        static staticFn() {
            super.staticFn();
            expect.step("extension.staticFn");
        }
        setup() {
            super.setup();
            expect.step("extension.setup");
        }
        fn() {
            super.fn();
            expect.step("extension.fn");
        }
    };
}

describe.current.tags("headless");

test("one patch/unpatch", () => {
    new BaseClass().fn();
    expect.verifySteps(["base.setup", "base.fn"]);

    const unpatch = applyGenericPatch(BaseClass, "patch");
    new BaseClass().fn();
    expect.verifySteps(["base.setup", "patch.setup", "base.fn", "patch.fn"]);

    unpatch();
    new BaseClass().fn();
    expect.verifySteps(["base.setup", "base.fn"]);
});

test("two patch/unpatch (unpatch 1 > 2)", () => {
    new BaseClass().fn();
    expect.verifySteps(["base.setup", "base.fn"]);

    const unpatch1 = applyGenericPatch(BaseClass, "patch1");
    new BaseClass().fn();
    expect.verifySteps(["base.setup", "patch1.setup", "base.fn", "patch1.fn"]);

    const unpatch2 = applyGenericPatch(BaseClass, "patch2");
    new BaseClass().fn();
    expect.verifySteps([
        "base.setup",
        "patch1.setup",
        "patch2.setup",
        "base.fn",
        "patch1.fn",
        "patch2.fn",
    ]);

    unpatch1();
    new BaseClass().fn();
    expect.verifySteps(["base.setup", "patch2.setup", "base.fn", "patch2.fn"]);

    unpatch2();
    new BaseClass().fn();
    expect.verifySteps(["base.setup", "base.fn"]);
});

test("two patch/unpatch (unpatch 2 > 1)", () => {
    new BaseClass().fn();
    expect.verifySteps(["base.setup", "base.fn"]);

    const unpatch1 = applyGenericPatch(BaseClass, "patch1");
    new BaseClass().fn();
    expect.verifySteps(["base.setup", "patch1.setup", "base.fn", "patch1.fn"]);

    const unpatch2 = applyGenericPatch(BaseClass, "patch2");
    new BaseClass().fn();
    expect.verifySteps([
        "base.setup",
        "patch1.setup",
        "patch2.setup",
        "base.fn",
        "patch1.fn",
        "patch2.fn",
    ]);

    unpatch2();
    new BaseClass().fn();
    expect.verifySteps(["base.setup", "patch1.setup", "base.fn", "patch1.fn"]);

    unpatch1();
    new BaseClass().fn();
    expect.verifySteps(["base.setup", "base.fn"]);
});

test("patch for specialization", () => {
    let args = [];
    class A {
        constructor() {
            this.setup(...arguments);
        }
        setup() {
            args = ["A", ...arguments];
        }
    }

    const unpatch = patch(A.prototype, {
        setup() {
            super.setup("patch", ...arguments);
        },
    });

    new A("instantiation");
    expect(args).toEqual(["A", "patch", "instantiation"]);
    unpatch();
});

test("instance fields", () => {
    const unpatch = patch(BaseClass.prototype, {
        setup() {
            super.setup();
            this.str += "patch";
            this.arr.push("patch");
            this.obj.patch = "patch";
        },
    });

    const instance = new BaseClass();
    expect.verifySteps(["base.setup"]);
    expect(instance.str).toBe("basepatch");
    expect(instance.arr).toEqual(["base", "patch"]);
    expect(instance.obj).toEqual({ base: "base", patch: "patch" });

    unpatch();
    expect(instance.str).toBe("basepatch");
    expect(instance.arr).toEqual(["base", "patch"]);
    expect(instance.obj).toEqual({ base: "base", patch: "patch" });
});

test("call instance method defined in patch", () => {
    const instance = new BaseClass();
    expect.verifySteps(["base.setup"]);
    expect(instance).not.toInclude("f");

    const unpatch = patch(BaseClass.prototype, {
        f() {
            expect.step("patch.f");
        },
    });
    instance.f();
    expect(instance).toInclude("f");
    expect.verifySteps(["patch.f"]);

    unpatch();
    expect(instance).not.toInclude("f");
});

test("class methods", () => {
    BaseClass.staticFn();
    expect.verifySteps(["base.staticFn"]);

    const unpatch = applyGenericStaticPatch(BaseClass, "patch");
    BaseClass.staticFn();
    expect.verifySteps(["base.staticFn", "patch.staticFn"]);

    unpatch();
    BaseClass.staticFn();
    expect.verifySteps(["base.staticFn"]);
});

test("class fields", () => {
    expect(BaseClass.staticStr).toBe("base");
    expect(BaseClass.staticArr).toEqual(["base"]);
    expect(BaseClass.staticObj).toEqual({ base: "base" });

    const unpatch = applyGenericStaticPatch(BaseClass, "patch");
    expect(BaseClass.staticStr).toBe("basepatch");
    expect(BaseClass.staticArr).toEqual(["base", "patch"]);
    expect(BaseClass.staticObj).toEqual({ base: "base", patch: "patch" });

    unpatch();
    expect(BaseClass.staticStr).toBe("base");
    expect(BaseClass.staticArr).toEqual(["base"]);
    expect(BaseClass.staticObj).toEqual({ base: "base" });
});

test("lazy patch", () => {
    const instance = new BaseClass();
    const unpatch = applyGenericPatch(BaseClass, "patch");
    instance.fn();
    expect.verifySteps(["base.setup", "base.fn", "patch.fn"]);

    unpatch();
    instance.fn();
    expect.verifySteps(["base.fn"]);
});

test("getter", () => {
    const instance = new BaseClass();
    expect.verifySteps(["base.setup"]);
    expect(instance.dynamic).toBe("base");

    const unpatch = patch(BaseClass.prototype, {
        get dynamic() {
            return super.dynamic + "patch";
        },
    });
    expect(instance.dynamic).toBe("basepatch");

    unpatch();
    expect(instance.dynamic).toBe("base");
});

test("setter", () => {
    const instance = new BaseClass();
    expect.verifySteps(["base.setup"]);
    expect(instance.dynamic).toBe("base");
    instance.dynamic = "1";
    expect(instance.dynamic).toBe("1");

    const unpatch = patch(BaseClass.prototype, {
        set dynamic(value) {
            super.dynamic = "patch:" + value;
        },
    });
    expect(instance.dynamic).toBe("1");

    instance.dynamic = "2";
    expect(instance.dynamic).toBe("patch:2");

    unpatch();
    instance.dynamic = "3";
    expect(instance.dynamic).toBe("3");
});

test("patch getter/setter with value", () => {
    const originalDescriptor = Object.getOwnPropertyDescriptor(
        BaseClass.prototype,
        "dynamic",
    );

    const unpatch = patch(BaseClass.prototype, { dynamic: "patched" });
    const instance = new BaseClass();
    expect.verifySteps(["base.setup"]);
    expect(Object.getOwnPropertyDescriptor(BaseClass.prototype, "dynamic")).toEqual({
        value: "patched",
        writable: true,
        configurable: true,
        enumerable: false,
    });
    expect(instance.dynamic).toBe("patched");

    unpatch();
    instance.dynamic = "base";
    expect(Object.getOwnPropertyDescriptor(BaseClass.prototype, "dynamic")).toEqual(
        originalDescriptor,
    );
    expect(instance.dynamic).toBe("base");
});

test("async function", async () => {
    const instance = new BaseClass();
    instance.str = "async1";
    await instance.asyncFn();
    expect.verifySteps(["base.setup", "base.async1"]);

    const unpatch = applyGenericPatch(BaseClass, "patch");
    instance.str = "async2";
    await instance.asyncFn();
    expect.verifySteps(["base.async2", "patch.async2"]);

    unpatch();
    instance.str = "async3";
    await instance.asyncFn();
    expect.verifySteps(["base.async3"]);
});

test("async function (multiple patches)", async () => {
    const instance = new BaseClass();
    instance.str = "async1";
    await instance.asyncFn();
    expect.verifySteps(["base.setup", "base.async1"]);

    const unpatch1 = applyGenericPatch(BaseClass, "patch1");
    const unpatch2 = applyGenericPatch(BaseClass, "patch2");
    instance.str = "async2";
    await instance.asyncFn();
    expect.verifySteps(["base.async2", "patch1.async2", "patch2.async2"]);

    unpatch1();
    unpatch2();
    instance.str = "async3";
    await instance.asyncFn();
    expect.verifySteps(["base.async3"]);
});

test("call another super method", () => {
    new BaseClass();
    expect.verifySteps(["base.setup"]);

    const unpatch = patch(BaseClass.prototype, {
        setup() {
            expect.step("patch.setup");
            super.fn();
        },
        fn() {
            expect.step("patch.fn");
        },
    });

    new BaseClass();
    expect.verifySteps(["patch.setup", "base.fn"]);

    unpatch();
    new BaseClass();
    expect.verifySteps(["base.setup"]);
});

describe("inheritance", () => {
    test("extend > patch base > unpatch base", () => {
        const Extension = createGenericExtension();
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "extension.setup",
            "base.fn",
            "extension.fn",
        ]);

        const unpatch = applyGenericPatch(BaseClass, "patch");
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "patch.setup",
            "extension.setup",
            "base.fn",
            "patch.fn",
            "extension.fn",
        ]);

        unpatch();
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "extension.setup",
            "base.fn",
            "extension.fn",
        ]);
    });

    test("patch base > extend > unpatch base", () => {
        const unpatch = applyGenericPatch(BaseClass, "patch");
        const Extension = createGenericExtension();
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "patch.setup",
            "extension.setup",
            "base.fn",
            "patch.fn",
            "extension.fn",
        ]);

        unpatch();
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "extension.setup",
            "base.fn",
            "extension.fn",
        ]);
    });

    test("extend > patch extension > unpatch extension", () => {
        const Extension = createGenericExtension();
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "extension.setup",
            "base.fn",
            "extension.fn",
        ]);

        const unpatch = applyGenericPatch(Extension, "patch.extension");
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "extension.setup",
            "patch.extension.setup",
            "base.fn",
            "extension.fn",
            "patch.extension.fn",
        ]);

        unpatch();
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "extension.setup",
            "base.fn",
            "extension.fn",
        ]);
    });

    test("extend > patch base > patch extension > unpatch base > unpatch extension", () => {
        const Extension = createGenericExtension();
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "extension.setup",
            "base.fn",
            "extension.fn",
        ]);

        const unpatchBase = applyGenericPatch(BaseClass, "patch");
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "patch.setup",
            "extension.setup",
            "base.fn",
            "patch.fn",
            "extension.fn",
        ]);

        const unpatchExtension = applyGenericPatch(Extension, "patch.extension");
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "patch.setup",
            "extension.setup",
            "patch.extension.setup",
            "base.fn",
            "patch.fn",
            "extension.fn",
            "patch.extension.fn",
        ]);

        unpatchBase();
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "extension.setup",
            "patch.extension.setup",
            "base.fn",
            "extension.fn",
            "patch.extension.fn",
        ]);

        unpatchExtension();
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "extension.setup",
            "base.fn",
            "extension.fn",
        ]);
    });

    test("extend > patch base > patch extension > unpatch extension > unpatch base", () => {
        const Extension = createGenericExtension();
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "extension.setup",
            "base.fn",
            "extension.fn",
        ]);

        const unpatchBase = applyGenericPatch(BaseClass, "patch");
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "patch.setup",
            "extension.setup",
            "base.fn",
            "patch.fn",
            "extension.fn",
        ]);

        const unpatchExtension = applyGenericPatch(Extension, "patch.extension");
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "patch.setup",
            "extension.setup",
            "patch.extension.setup",
            "base.fn",
            "patch.fn",
            "extension.fn",
            "patch.extension.fn",
        ]);

        unpatchExtension();
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "patch.setup",
            "extension.setup",
            "base.fn",
            "patch.fn",
            "extension.fn",
        ]);

        unpatchBase();
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "extension.setup",
            "base.fn",
            "extension.fn",
        ]);
    });

    test("extend > patch extension > patch base > unpatch base > unpatch extension", () => {
        const Extension = createGenericExtension();
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "extension.setup",
            "base.fn",
            "extension.fn",
        ]);

        const unpatchExtension = applyGenericPatch(Extension, "patch.extension");
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "extension.setup",
            "patch.extension.setup",
            "base.fn",
            "extension.fn",
            "patch.extension.fn",
        ]);

        const unpatchBase = applyGenericPatch(BaseClass, "patch");
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "patch.setup",
            "extension.setup",
            "patch.extension.setup",
            "base.fn",
            "patch.fn",
            "extension.fn",
            "patch.extension.fn",
        ]);

        unpatchBase();
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "extension.setup",
            "patch.extension.setup",
            "base.fn",
            "extension.fn",
            "patch.extension.fn",
        ]);

        unpatchExtension();
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "extension.setup",
            "base.fn",
            "extension.fn",
        ]);
    });

    test("extend > patch extension > patch base > unpatch extension > unpatch base", () => {
        const Extension = createGenericExtension();
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "extension.setup",
            "base.fn",
            "extension.fn",
        ]);

        const unpatchExtension = applyGenericPatch(Extension, "patch.extension");
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "extension.setup",
            "patch.extension.setup",
            "base.fn",
            "extension.fn",
            "patch.extension.fn",
        ]);

        const unpatchBase = applyGenericPatch(BaseClass, "patch");
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "patch.setup",
            "extension.setup",
            "patch.extension.setup",
            "base.fn",
            "patch.fn",
            "extension.fn",
            "patch.extension.fn",
        ]);

        unpatchExtension();
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "patch.setup",
            "extension.setup",
            "base.fn",
            "patch.fn",
            "extension.fn",
        ]);

        unpatchBase();
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "extension.setup",
            "base.fn",
            "extension.fn",
        ]);
    });

    test("patch base > extend > patch extension > unpatch base > unpatch extension", () => {
        const unpatchBase = applyGenericPatch(BaseClass, "patch");
        const Extension = createGenericExtension();
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "patch.setup",
            "extension.setup",
            "base.fn",
            "patch.fn",
            "extension.fn",
        ]);

        const unpatchExtension = applyGenericPatch(Extension, "patch.extension");
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "patch.setup",
            "extension.setup",
            "patch.extension.setup",
            "base.fn",
            "patch.fn",
            "extension.fn",
            "patch.extension.fn",
        ]);

        unpatchBase();
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "extension.setup",
            "patch.extension.setup",
            "base.fn",
            "extension.fn",
            "patch.extension.fn",
        ]);

        unpatchExtension();
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "extension.setup",
            "base.fn",
            "extension.fn",
        ]);
    });

    test("patch base > extend > patch extension > unpatch extension > unpatch base", () => {
        const unpatchBase = applyGenericPatch(BaseClass, "patch");
        const Extension = createGenericExtension();
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "patch.setup",
            "extension.setup",
            "base.fn",
            "patch.fn",
            "extension.fn",
        ]);

        const unpatchExtension = applyGenericPatch(Extension, "patch.extension");
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "patch.setup",
            "extension.setup",
            "patch.extension.setup",
            "base.fn",
            "patch.fn",
            "extension.fn",
            "patch.extension.fn",
        ]);

        unpatchExtension();
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "patch.setup",
            "extension.setup",
            "base.fn",
            "patch.fn",
            "extension.fn",
        ]);

        unpatchBase();
        new Extension().fn();
        expect.verifySteps([
            "base.setup",
            "extension.setup",
            "base.fn",
            "extension.fn",
        ]);
    });

    test("class methods", () => {
        const Extension = createGenericExtension();
        Extension.staticFn();
        expect.verifySteps(["base.staticFn", "extension.staticFn"]);

        const unpatchBase = applyGenericStaticPatch(BaseClass, "patch");
        Extension.staticFn();
        expect.verifySteps(["base.staticFn", "patch.staticFn", "extension.staticFn"]);

        const unpatchExtension = applyGenericStaticPatch(Extension, "patch.extension");
        Extension.staticFn();
        expect.verifySteps([
            "base.staticFn",
            "patch.staticFn",
            "extension.staticFn",
            "patch.extension.staticFn",
        ]);

        unpatchBase();
        Extension.staticFn();
        expect.verifySteps([
            "base.staticFn",
            "extension.staticFn",
            "patch.extension.staticFn",
        ]);

        unpatchExtension();
        Extension.staticFn();
        expect.verifySteps(["base.staticFn", "extension.staticFn"]);
    });

    test("class fields (patch before inherit)", () => {
        const unpatch = applyGenericStaticPatch(BaseClass, "patch");
        const Extension = createGenericExtension();
        expect(Extension.staticStr).toBe("basepatchextension");
        expect(Extension.staticArr).toEqual(["base", "patch", "extension"]);
        expect(Extension.staticObj).toEqual({
            base: "base",
            patch: "patch",
            extension: "extension",
        });

        unpatch();
        expect(Extension.staticStr).toBe("basepatchextension");
        expect(Extension.staticArr).toEqual(["base", "patch", "extension"]);
        expect(Extension.staticObj).toEqual({
            base: "base",
            patch: "patch",
            extension: "extension",
        });
    });

    test("class fields (inherit before patch)", () => {
        const Extension = createGenericExtension();
        expect(Extension.staticStr).toBe("baseextension");
        expect(Extension.staticArr).toEqual(["base", "extension"]);
        expect(Extension.staticObj).toEqual({ base: "base", extension: "extension" });

        const unpatch = applyGenericStaticPatch(BaseClass, "patch");
        expect(Extension.staticStr).toBe("baseextension");
        expect(Extension.staticArr).toEqual(["base", "extension"]);
        expect(Extension.staticObj).toEqual({ base: "base", extension: "extension" });

        unpatch();
        expect(Extension.staticStr).toBe("baseextension");
        expect(Extension.staticArr).toEqual(["base", "extension"]);
        expect(Extension.staticObj).toEqual({ base: "base", extension: "extension" });
    });

    test("lazy patch", () => {
        const Extension = createGenericExtension();
        const instance = new Extension();
        const unpatch = applyGenericPatch(BaseClass, "patch");

        instance.fn();
        expect.verifySteps([
            "base.setup",
            "extension.setup",
            "base.fn",
            "patch.fn",
            "extension.fn",
        ]);

        unpatch();
        instance.fn();
        expect.verifySteps(["base.fn", "extension.fn"]);
    });

    test("keep original descriptor details", () => {
        class Klass {
            get getter() {
                return false;
            }
        }
        let descriptor = Object.getOwnPropertyDescriptor(Klass.prototype, "getter");
        const getterFn = descriptor.get;
        expect(descriptor.configurable).toBe(true);
        expect(descriptor.enumerable).toBe(false);

        patch(Klass.prototype, {
            get getter() {
                return true;
            },
        });
        descriptor = Object.getOwnPropertyDescriptor(Klass.prototype, "getter");
        expect(descriptor.configurable).toBe(true);
        expect(descriptor.enumerable).toBe(false);
        expect(getterFn).not.toBe(descriptor.get);
    });
});

describe("other", () => {
    test("patch an object", () => {
        const obj = {
            var: "obj",
            fn() {
                expect.step("obj");
            },
        };

        const unpatch = patch(obj, {
            var: obj.var + "patch",
            fn() {
                super.fn();
                expect.step("patch");
            },
        });
        expect(obj.var).toBe("objpatch");

        obj.fn();
        expect.verifySteps(["obj", "patch"]);

        unpatch();
        expect(obj.var).toBe("obj");

        obj.fn();
        expect.verifySteps(["obj"]);
    });

    test("can call a non bound patched method", () => {
        const obj = {
            fn() {
                expect.step("original");
            },
        };

        const originalFn = obj.fn;
        patch(obj, {
            fn() {
                expect.step("patched");
                originalFn();
            },
        });

        const fn = obj.fn;
        fn();
        expect.verifySteps(["patched", "original"]);
    });
});

describe("patchInfo", () => {
    test("unpatched target returns null", () => {
        const obj = { fn() {} };
        expect(patchInfo(obj)).toBe(null);
    });

    test("reports extensions in call order with patched keys", () => {
        const obj = { var: "v", fn() {} };
        const ext1 = { var: "v1" };
        const ext2 = { fn() {} };

        patch(obj, ext1);
        patch(obj, ext2);

        const info = patchInfo(obj);
        expect(info.extensions).toEqual([ext1, ext2]);
        expect(info.patchedKeys).toEqual(["var", "fn"]);
    });

    test("returns null after every patch is unpatched", () => {
        const obj = { fn() {} };
        const unpatch1 = patch(obj, { fn() {} });
        const unpatch2 = patch(obj, { fn() {} });

        expect(patchInfo(obj).extensions).toHaveLength(2);

        unpatch1();
        expect(patchInfo(obj).extensions).toHaveLength(1);

        unpatch2();
        expect(patchInfo(obj)).toBe(null);
    });

    test("returned extensions array is a copy — mutating it leaves the patch graph intact", () => {
        const obj = { fn() {} };
        const ext = { fn() {} };
        patch(obj, ext);

        const info = patchInfo(obj);
        info.extensions.length = 0;

        expect(patchInfo(obj).extensions).toEqual([ext]);
    });

    test("works on class prototypes and on class constructors independently", () => {
        class A {
            fn() {}
            static staticFn() {}
        }
        const protoPatch = { fn() {} };
        const staticPatch = { staticFn() {} };

        patch(A.prototype, protoPatch);
        patch(A, staticPatch);

        expect(patchInfo(A.prototype).extensions).toEqual([protoPatch]);
        expect(patchInfo(A).extensions).toEqual([staticPatch]);
        expect(patchInfo(A.prototype).patchedKeys).toEqual(["fn"]);
        expect(patchInfo(A).patchedKeys).toEqual(["staticFn"]);
    });
});

describe("single-use extension", () => {
    test("patching the same target twice with the same extension throws a clear error", () => {
        class A {
            fn() {
                return "base";
            }
        }
        const ext = {
            fn() {
                return "patch:" + super.fn();
            },
        };
        patch(A.prototype, ext);
        expect(() => patch(A.prototype, ext)).toThrow(/already used in a patch/);
        expect(() => patch(A.prototype, ext)).not.toThrow(/Cyclic/);
    });

    test("sharing one extension across two targets throws and leaves the first intact", () => {
        class A {
            fn() {
                return "a";
            }
        }
        class B {
            fn() {
                return "b";
            }
        }
        const shared = {
            fn() {
                return "s:" + super.fn();
            },
        };
        patch(A.prototype, shared);
        expect(new A().fn()).toBe("s:a");
        expect(() => patch(B.prototype, shared)).toThrow(/already used in a patch/);
        expect(new A().fn()).toBe("s:a");
    });

    test("unpatch still re-applies surviving extensions (fresh objects each)", () => {
        class A {
            fn() {
                return "a";
            }
        }
        const unpatch1 = patch(A.prototype, {
            fn() {
                return "1:" + super.fn();
            },
        });
        patch(A.prototype, {
            fn() {
                return "2:" + super.fn();
            },
        });
        expect(new A().fn()).toBe("2:1:a");
        unpatch1();
        expect(new A().fn()).toBe("2:a");
    });
});

describe("extension objects stay pristine", () => {
    test("patching a second key does not stamp it onto the first extension", () => {
        class A {
            foo() {
                return "foo";
            }
            bar() {
                return "bar";
            }
        }
        const extFoo = {
            foo() {
                return "F:" + super.foo();
            },
        };
        const extBar = {
            bar() {
                return "B:" + super.bar();
            },
        };
        const unFoo = patch(A.prototype, extFoo);
        const unBar = patch(A.prototype, extBar);

        // `patch()` used to reuse the previous extension as the skeleton store,
        // so `extFoo` came back owning a `bar` it never declared. The
        // double-patch audit in mail/ had to work around that.
        expect(Object.getOwnPropertyNames(extFoo)).toEqual(["foo"]);
        expect(Object.getOwnPropertyNames(extBar)).toEqual(["bar"]);

        const a = new A();
        expect(a.foo()).toBe("F:foo");
        expect(a.bar()).toBe("B:bar");
        unBar();
        unFoo();
        expect(a.foo()).toBe("foo");
        expect(a.bar()).toBe("bar");
    });

    test("same key, two extensions, unpatched in either order", () => {
        class A {
            fn() {
                return "orig";
            }
        }
        const unA = patch(A.prototype, {
            fn() {
                return "A>" + super.fn();
            },
        });
        const unB = patch(A.prototype, {
            fn() {
                return "B>" + super.fn();
            },
        });
        expect(new A().fn()).toBe("B>A>orig");
        unA();
        expect(new A().fn()).toBe("B>orig");
        unB();
        expect(new A().fn()).toBe("orig");
    });

    test("a getter-only patch keeps the ancestor setter", () => {
        const base = {
            _v: 1,
            get v() {
                return this._v;
            },
            set v(x) {
                this._v = x;
            },
        };
        const target = Object.create(base);
        const un = patch(target, {
            get v() {
                return super.v * 10;
            },
        });
        expect(target.v).toBe(10);
        target.v = 5;
        expect(target.v).toBe(50);
        un();
        expect(target.v).toBe(5);
    });

    test("calling an unpatch twice is a no-op", () => {
        class A {
            fn() {
                return "orig";
            }
        }
        const unA = patch(A.prototype, {
            fn() {
                return "A>" + super.fn();
            },
        });
        const unB = patch(A.prototype, {
            fn() {
                return "B>" + super.fn();
            },
        });
        unB();
        unB();
        expect(new A().fn()).toBe("A>orig");
        expect(patchInfo(A.prototype).extensions).toHaveLength(1);
        unA();
        expect(new A().fn()).toBe("orig");
        expect(patchInfo(A.prototype)).toBe(null);
    });

    test("a stale unpatch leaves a later, unrelated patch alone", () => {
        class A {
            fn() {
                return "orig";
            }
        }
        const unA = patch(A.prototype, {
            fn() {
                return "A>" + super.fn();
            },
        });
        unA();
        expect(new A().fn()).toBe("orig");

        // Another module patches the same target afterwards. The first
        // unpatch no longer owns anything here and must not touch it.
        const unC = patch(A.prototype, {
            fn() {
                return "C>" + super.fn();
            },
        });
        unA();
        expect(new A().fn()).toBe("C>orig");
        expect(patchInfo(A.prototype).extensions).toHaveLength(1);

        // ...and C's own unpatch still works, rather than having been
        // silently deregistered.
        unC();
        expect(new A().fn()).toBe("orig");
        expect(patchInfo(A.prototype)).toBe(null);
    });
});

describe("mixin chains", () => {
    // `SearchModel` is
    // `SearchQueryMixin(SearchSplitDomainMixin(SearchFavoritesMixin(
    //     SearchPropertiesMixin(SearchPanelMixin(EventBus)))))`
    // — five mixins holding 1,139 lines of class body. Every method they declare
    // lives on an ANCESTOR prototype, not on `SearchModel.prototype`, so patching
    // the composed class for one of those names is the case where `patch()` finds
    // no own descriptor to record on its skeleton and `super` must resolve through
    // the real prototype chain instead.
    //
    // Nothing else in this file covers that: every other test patches a key the
    // target itself declares. The whole extensibility argument for mixin-composed
    // classes rests on this working, so it is pinned here rather than assumed.

    const withDeep = (Base) =>
        class extends Base {
            deep() {
                expect.step("deep.mixin");
            }
            get deepValue() {
                return "mixin";
            }
        };
    const withMiddle = (Base) =>
        class extends Base {
            deep() {
                super.deep();
                expect.step("middle.mixin");
            }
        };

    function createComposed() {
        return class Composed extends withMiddle(withDeep(class {})) {};
    }

    test("patch a composed class for a method declared only in a mixin", () => {
        const Composed = createComposed();
        expect(Object.hasOwn(Composed.prototype, "deep")).toBe(false);

        new Composed().deep();
        expect.verifySteps(["deep.mixin", "middle.mixin"]);

        const unpatch = patch(Composed.prototype, {
            deep() {
                super.deep();
                expect.step("patch.deep");
            },
        });
        new Composed().deep();
        expect.verifySteps(["deep.mixin", "middle.mixin", "patch.deep"]);

        unpatch();
        new Composed().deep();
        expect.verifySteps(["deep.mixin", "middle.mixin"]);
    });

    test("patch a getter declared only in a mixin", () => {
        const Composed = createComposed();
        expect(new Composed().deepValue).toBe("mixin");

        const unpatch = patch(Composed.prototype, {
            get deepValue() {
                return `${super.deepValue}+patch`;
            },
        });
        expect(new Composed().deepValue).toBe("mixin+patch");

        unpatch();
        expect(new Composed().deepValue).toBe("mixin");
    });

    test("two patches on a mixin-declared method chain in order", () => {
        const Composed = createComposed();
        const unpatch1 = patch(Composed.prototype, {
            deep() {
                super.deep();
                expect.step("patch1.deep");
            },
        });
        const unpatch2 = patch(Composed.prototype, {
            deep() {
                super.deep();
                expect.step("patch2.deep");
            },
        });
        new Composed().deep();
        expect.verifySteps([
            "deep.mixin",
            "middle.mixin",
            "patch1.deep",
            "patch2.deep",
        ]);

        unpatch2();
        unpatch1();
        new Composed().deep();
        expect.verifySteps(["deep.mixin", "middle.mixin"]);
    });
});
