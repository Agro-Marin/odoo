import { Component } from "@odoo/owl";

interface Assert {
    containsN(target: HTMLElement, selector: String, n: Number, msg?: string): void;

    containsNone(target: HTMLElement, selector: String, msg?: string): void;

    containsOnce(target: HTMLElement, selector: String, msg?: string): void;

    /**
     * @private
     * @param {HTMLElement|jQuery|Widget} el
     */
    _checkClass(
        el: HTMLElement,
        classNames: String,
        shouldHaveClass: boolean,
        msg?: string,
    ): void;

    hasClass(el: HTMLElement, classNames: String, msg?: string): void;

    doesNotHaveClass(el: HTMLElement, classNames: String, msg?: string): void;

    /**
     * @param {Widget|jQuery|HTMLElement|Component} target
     */
    hasAttrValue(target: HTMLElement, attr: string, value: string, msg?: string): void;

    /**
     * @private
     * @param {HTMLElement|jQuery|Widget} el
     */
    _checkVisible(el: HTMLElement, shouldBeVisible: boolean, msg?: string): void;

    /**
     * @param {HTMLElement|jQuery|Widget} el
     */
    isVisible(el: HTMLElement, msg?: string): void;

    /**
     * @param {HTMLElement|jQuery|Widget} el
     */
    isNotVisible(el: HTMLElement, msg?: string): void;

    /**
     * @param {number} [acceptCallCount=1] Number of expected callbacks before the test is done.
     */
    async(acceptCallCount?: number): () => void;

    /**
     * @param actual Object or Expression being tested
     * @param expected Known comparision value
     * @param {string} [message] A short description of the assertion
     */
    deepEqual<T>(actual: T, expected: T, message?: string): void;

    /**
     * @param actual Expression being tested
     * @param expected Known comparison value
     * @param {string} [message] A short description of the assertion
     */
    equal(actual: any, expected: any, message?: string): void;

    /**
     * @param {number} amount Number of assertions in this test.
     */
    expect(amount: number): void;

    /**
     * @param actual Object or Expression being tested
     * @param expected Known comparison value
     * @param {string} [message] A short description of the assertion
     */
    notDeepEqual(actual: any, expected: any, message?: string): void;

    /**
     * @param actual Object or Expression being tested
     * @param expected Known comparison value
     * @param {string} [message] A short description of the assertion
     */
    notEqual(actual: any, expected: any, message?: string): void;

    /**
     * @param state Expression being tested
     * @param {string} [message] A short description of the assertion
     */
    notOk(state: any, message?: string): void;

    /**
     * @param actual Object or Expression being tested
     * @param expected Known comparison value
     * @param {string} [message] A short description of the assertion
     */
    notPropEqual(actual: any, expected: any, message?: string): void;

    /**
     * @param actual Object or Expression being tested
     * @param expected Known comparison value
     * @param {string} [message] A short description of the assertion
     */
    notStrictEqual(actual: any, expected: any, message?: string): void;

    /**
     * @param state Expression being tested
     * @param {string} message A short description of the assertion
     */
    ok(state: any, message?: string): void;

    /**
     * @param actual Object or Expression being tested
     * @param expected Known comparison value
     * @param {string} [message] A short description of the assertion
     */
    propEqual(actual: any, expected: any, message?: string): void;

    /**
     * @param assertionResult The assertion result
     */
    pushResult(assertResult: {
        result: boolean;
        actual: any;
        expected: any;
        message: string;
    }): void;

    /**
     * @param actual Object or Expression being tested
     * @param expected Known comparison value
     * @param {string} [message] A short description of the assertion
     */
    strictEqual<T>(actual: T, expected: T, message?: string): void;

    throws(block: () => void, expected?: any, message?: any): void;
    raises(block: () => void, expected?: any, message?: any): void;

    /**
     * @param promise promise to test for rejection
     * @param expectedMatcher Rejection value matcher
     * @param message A short description of the assertion
     */
    rejects(promise: Promise<any>, message?: string): Promise<void>;
    rejects(
        promise: Promise<any>,
        expectedMatcher?: any,
        message?: string,
    ): Promise<void>;

    /**
     * @param message Message to display for the step
     */
    step(message: string): void;

    /**
     * @param steps Array of strings representing steps to verify
     * @param message A short description of the assertion
     */
    verifySteps(steps: string[], message?: string): void;
}

interface Config {
    altertitle: boolean;
    autostart: boolean;
    collapse: boolean;
    current: any;
    filter: string | RegExp;
    fixture: string;
    hidepassed: boolean;
    maxDepth: number;
    module: string;
    moduleId: string[];
    notrycatch: boolean;
    noglobals: boolean;
    seed: string;
    reorder: boolean;
    requireExpects: boolean;
    testId: string[];
    testTimeout: number;
    scrolltop: boolean;
    urlConfig: {
        id?: string;
        label?: string;
        tooltip?: string;
        value?: string | string[] | { [key: string]: string };
    }[];
}

interface Hooks {
    after?: (assert: Assert) => void | Promise<void>;

    afterEach?: (assert: Assert) => void | Promise<void>;

    before?: (assert: Assert) => void | Promise<void>;

    beforeEach?: (assert: Assert) => void | Promise<void>;
}

interface NestedHooks {
    after: (fn: (assert: Assert) => void | Promise<void>) => void;

    afterEach: (fn: (assert: Assert) => void | Promise<void>) => void;

    before: (fn: (assert: Assert) => void | Promise<void>) => void;

    beforeEach: (fn: (assert: Assert) => void | Promise<void>) => void;
}

type moduleFunc1 = (
    name: string,
    hooks?: Hooks,
    nested?: (hooks: NestedHooks) => void,
) => void;
type moduleFunc2 = (name: string, nested?: (hooks: NestedHooks) => void) => void;
type ModuleOnly = { only: moduleFunc1 & moduleFunc2 };

declare namespace QUnitNamespace {
    interface BeginDetails {
        totalTests: number;
    }
    interface DoneDetails {
        failed: number;
        passed: number;
        total: number;
        runtime: number;
    }
    interface LogDetails {
        result: boolean;
        actual: any;
        expected: any;
        message: string;
        source: string;
        module: string;
        name: string;
        runtime: number;
    }
    interface ModuleDoneDetails {
        name: string;
        failed: number;
        passed: number;
        total: number;
        runtime: number;
    }
    interface ModuleStartDetails {
        name: string;
    }
    interface TestDoneDetails {
        name: string;
        module: string;
        failed: number;
        passed: number;
        total: number;
        runtime: number;
    }
    interface TestStartDetails {
        name: string;
        module: string;
    }
}

interface QUnit {
    assert: Assert;

    /**
     * @callback callback Callback to execute.
     */
    begin(
        callback: (details: QUnitNamespace.BeginDetails) => void | Promise<void>,
    ): void;

    config: Config;

    /**
     * @param callback Callback to execute
     */
    done(callback: (details: QUnitNamespace.DoneDetails) => void | Promise<void>): void;

    dump: {
        maxDepth: number;
        parse(data: any): string;
    };

    /**
     * @param target An object whose properties are to be modified
     * @param mixin An object describing which properties should be modified
     */
    extend(target: any, mixin: any): void;

    /**
     * @param callback Callback to execute
     */
    log(callback: (details: QUnitNamespace.LogDetails) => void): void;

    /**
     * @param {string} name Label for this group of tests
     * @param hookds Callbacks to run during test execution
     * @param nested A callback with grouped tests and nested modules to run under the current module label
     */
    module: moduleFunc1 & moduleFunc2 & ModuleOnly;

    /**
     * @param callback Callback to execute
     */
    moduleDone(
        callback: (details: QUnitNamespace.ModuleDoneDetails) => void | Promise<void>,
    ): void;

    /**
     * @param callback Callback to execute
     */
    moduleStart(
        callback: (details: QUnitNamespace.ModuleStartDetails) => void | Promise<void>,
    ): void;

    /**
     * @param {string} name Title of unit being tested
     * @param callback Function to close over assertions
     */
    only(name: string, callback: (assert: Assert) => void | Promise<void>): void;

    /**
     * @param {string} name Title of unit being tested
     * @param callback Function to close over assertions
     */
    debug(name: string, callback: (assert: Assert) => void | Promise<void>): void;

    /**
     * @deprecated
     */
    push(result: boolean, actual: any, expected: any, message: string): void;

    /**
     * @param {string} Title of unit being tested
     */
    skip(name: string, callback?: (assert: Assert) => void | Promise<void>): void;

    /**
     * @param {number} offset Set the stacktrace line offset.
     */
    stack(offset?: number): string;

    start(): void;

    /**
     * @param {string} Title of unit being tested
     * @param callback Function to close over assertions
     */
    test(name: string, callback: (assert: Assert) => void | Promise<void>): void;

    /**
     * @param callback Callback to execute
     */
    testDone(
        callback: (details: {
            name: string;
            module: string;
            failed: number;
            passed: number;
            total: number;
            runtime: number;
        }) => void | Promise<void>,
    ): void;

    /**
     * @param callback Callback to execute
     */
    testStart(
        callback: (details: QUnitNamespace.TestStartDetails) => void | Promise<void>,
    ): void;

    /**
     * @param {string} Title of unit being tested
     * @param callback Function to close over assertions
     */
    todo(name: string, callback?: (assert: Assert) => void | Promise<void>): void;

    /**
     * @param a The first value
     * @param b The second value
     */
    equiv<T>(a: T, b: T): boolean;

    isLocal: boolean;

    version: string;
}
