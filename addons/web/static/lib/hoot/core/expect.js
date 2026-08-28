/** @odoo-module */

import {
    formatXml,
    getActiveElement,
    getNodeAttribute,
    getNodeRect,
    getNodeText,
    getNodeValue,
    getStyle,
    isCheckable,
    isEmpty,
    isNode,
    isNodeDisplayed,
    isNodeVisible,
    queryRect,
} from "@odoo/hoot-dom-helpers-dom";
import {
    addInteractionListener,
    getColorHex,
    isFirefox,
    isInstanceOf,
    isIterable,
    R_WHITE_SPACE,
} from "@odoo/hoot-dom-utils";
import { markRaw } from "@odoo/owl";

import {
    CASE_EVENT_TYPES,
    deepCopy,
    deepEqual,
    ElementMap,
    ensureArguments,
    ensureArray,
    formatHumanReadable,
    getConstructor,
    HootError,
    isLabel,
    isNil,
    isOfType,
    makeLabel,
    makeLabelIcon,
    Markup,
    match,
    S_ANY,
    S_NONE,
    strictEqual,
} from "../hoot_utils.js";
import { mockFetch } from "../mock/network.js";
import { logger } from "./logger.js";
import { Test } from "./test.js";

/**
 * @typedef {{
 *  aborted?: boolean;
 *  debug?: boolean;
 * }} AfterTestOptions
 * @typedef {import("../hoot_utils").ArgumentType} ArgumentType
 * @typedef {string | ((pass: boolean) => string)} AssertionMessage
 * @typedef {string | string[] | ((pass: boolean, raw: typeof String["raw"]) => string | string[])} AssertionReportMessage
 * @typedef {VerifierOptions & {
 *  timeout?: number;
 * }} AsyncVerifierOptions
 * @typedef {InteractionType | "assertion" | "error" | "step"} CaseEventType
 * @typedef {{ exact?: boolean }} ClassListOptions
 * @typedef {{ exact?: boolean; inline?: boolean }} DOMStyleOptions
 * @typedef {{
 *  headless: boolean;
 * }} ExpectBuilderParams
 * @typedef {{
 *  message?: AssertionMessage;
 *  not?: boolean;
 *  rejects?: boolean;
 *  resolves?: boolean;
 *  silent?: boolean;
 * }} ExpectOptions
 * @typedef {DeepEqualOptions & {
 *  message?: AssertionMessage;
 * }} VerifierOptions
 * @typedef {import("../hoot_utils").DeepEqualOptions} DeepEqualOptions
 * @typedef {import("../hoot_utils").Label} Label
 * @typedef {import("@odoo/hoot-dom").Dimensions} Dimensions
 * @typedef {import("@odoo/hoot-dom").FormatXmlOptions} FormatXmlOptions
 * @typedef {import("@odoo/hoot-dom-utils").InteractionDetails} InteractionDetails
 * @typedef {import("@odoo/hoot-dom-utils").InteractionType} InteractionType
 * @typedef {import("@odoo/hoot-dom").QueryRectOptions} QueryRectOptions
 * @typedef {import("@odoo/hoot-dom").QueryTextOptions} QueryTextOptions
 * @typedef {import("@odoo/hoot-dom").Target} Target
 */

/**
 * @template T
 * @typedef {T & ReturnType<Promise.withResolvers> & {
 *  options: VerifierOptions;
 *  timeout: number;
 * }} AsyncResolver
 */

/**
 * @template [R=unknown]
 * @template [A=R]
 * @typedef {{
 *  acceptedType: ArgumentType | ArgumentType[];
 *  getFailedDetails: () => unknown[];
 *  mapElements: (received: Target) => ElementMap;
 *  message: AssertionMessage;
 *  name: string;
 *  onFail: AssertionReportMessage;
 *  onPass: AssertionReportMessage;
 *  predicate: () => boolean;
 * }} MatcherSpecifications
 */

/**
 * @template T
 * @typedef {T | Iterable<T>} MaybeIterable
 */

const {
    Array: { isArray: $isArray },
    clearTimeout,
    Error,
    Intl: { ListFormat },
    Math: { abs: $abs, floor: $floor },
    Object: { assign: $assign, create: $create, entries: $entries, keys: $keys },
    parseFloat,
    performance,
    Promise,
    setTimeout,
    TypeError,
    WeakMap,
} = globalThis;
/** @type {Performance["now"]} */
const $now = performance.now.bind(performance);

/**
 * @param {[string, unknown][]} entries
 */
function detailsFromEntries(entries) {
    const result = [];
    const expected = entries.at(-2);
    if (expected) {
        result.push(Markup.expected(expected[0] || LABEL_EXPECTED, expected[1]));
    }
    const received = entries.at(-1);
    if (received) {
        result.push(Markup.received(received[0] || LABEL_RECEIVED, received[1]));
    }
    return result;
}

/**
 * @param {...unknown} args
 */
function detailsFromValues(...args) {
    return detailsFromEntries(args.map((arg) => [null, arg]));
}

/**
 * @param {...unknown} args
 */
function detailsFromValuesWithDiff(...args) {
    return detailsFromValues(...args).concat(Markup.diff(...args));
}

/**
 * @param {Error} [error]
 */
function formatError(error) {
    let strError = error ? String(error) : "";
    if (error?.cause) {
        strError += `\n${formatError(error.cause)}`;
    }
    return strError;
}

/**
 * @param {string} message
 * @param {boolean} plural
 * @param {boolean} not
 */
function formatMessage(message, plural, not) {
    return message
        .replaceAll(R_PLURAL, plural ? "$2" : "$1")
        .replaceAll(R_NOT, not ? "$2" : "$1");
}

/**
 * @param {Iterable<unknown> | Record<unknown, unknown>} object
 */
function getLength(object) {
    if (typeof object === "string" || $isArray(object)) {
        return object.length;
    }
    if (isIterable(object)) {
        return [...object].length;
    }
    return $keys(object).length;
}

/**
 * @param {number} depth
 */
function getStack(depth) {
    const error = new Error();
    if (!isFirefox()) {
        depth++;
    }
    const lines = error.stack.split(R_LINE_RETURN).slice(depth + 1);
    const hidden = lines.splice(MAX_STACK_LENGTH);
    if (hidden.length) {
        lines.push(`… ${hidden.length} more`);
    }
    return lines.join("\n");
}

/**
 * @param {Node} node
 * @param {string[]} keys
 * @returns {Record<string, string>}
 */
function getStyleValues(node, keys) {
    const nodeStyle = getStyle(node);
    const styleValues = $create(null);
    if (nodeStyle) {
        for (const key of keys) {
            styleValues[key] = nodeStyle.getPropertyValue(key) || nodeStyle[key];
        }
    }
    return styleValues;
}

/**
 * @param {Iterable<unknown> | Record<unknown, unknown>} object
 * @param {unknown} item
 * @returns {boolean}
 */
function includes(object, item) {
    if (typeof object === "string") {
        return object.includes(item);
    }
    if ($isArray(object)) {
        return object.some((i) => deepEqual(i, item));
    }
    if (isIterable(object)) {
        return includes([...object], item);
    }
    if ($isArray(item) && item.length === 2) {
        return includes($entries(object), item);
    }
    return item in object;
}

/**
 * @template T
 * @param {T[]} list
 * @param {string} separator
 * @param {string} [lastSeparator]
 * @returns {(T | string)[]}
 */
function listJoin(list, separator, lastSeparator) {
    if (list.length <= 1) {
        return list;
    }

    const rSeparator = isLabel(separator) ? separator : makeLabel(separator, null);
    const rLastSeparator = lastSeparator
        ? isLabel(lastSeparator)
            ? lastSeparator
            : makeLabel(lastSeparator, null)
        : rSeparator;

    const result = [];
    for (let i = 0; i < list.length; i++) {
        if (i === list.length - 1) {
            result.push(rLastSeparator);
        } else if (i > 0) {
            result.push(rSeparator);
        }
        result.push(list[i]);
    }
    return result;
}

/** @type {typeof makeLabel} */
function makeLabelOrString(...args) {
    const label = makeLabel(...args);
    if (logger.canLog("debug")) {
        debugLabelCache.set(label, args[0]);
    }
    return label[1] === null ? label[0] : label;
}

/**
 * @param {string} modifier
 * @param {string} message
 */
function matcherModifierError(modifier, message) {
    return new HootError(`cannot use modifier "${modifier}": ${message}`);
}

/**
 * @param {string | Record<string, unknown>} style
 * @param {unknown} [defaultValue]
 */
function parseInlineStyle(style, defaultValue) {
    /** @type {Record<string, string>} */
    const styleObject = $create(null);
    if (typeof style === "string") {
        for (const styleProperty of style.split(";")) {
            const [key, value] = styleProperty.split(":");
            if (key && (value ?? defaultValue)) {
                styleObject[key.trim()] = value?.trim() || defaultValue;
            }
        }
    } else {
        for (const key in style) {
            styleObject[key] = style[key];
        }
    }
    return styleObject;
}

/** @type {StringConstructor["raw"]} */
function r(template, ...substitutions) {
    return makeLabel(String.raw(template, ...substitutions), null);
}

/**
 * @param {string} method
 */
function scopeError(method) {
    return new HootError(`cannot call \`${method}()\` outside of a test`);
}

/**
 * @param {unknown} value
 * @param {string | number | RegExp} matcher
 */
function valueMatches(value, matcher) {
    if (matcher === S_ANY) {
        return !isNil(value);
    }
    if (isInstanceOf(matcher, RegExp)) {
        return matcher.test(value);
    }
    if (typeof matcher === "number") {
        value = parseFloat(value);
    }
    return strictEqual(value, matcher);
}

const AMPERSAND = makeLabel("&", null);
const ARROW_RIGHT = makeLabelIcon("fa-solid fa-arrow-right text-sm");

const R_LINE_RETURN = /\n+/g;
const R_NOT = /\[([\w\s]*)!([\w\s]*)\]/g;
const R_PLURAL = /\[([\w\s]*)%([\w\s]*)\]/g;

const FLAGS = {
    error: 0b1,
    headless: 0b10,
    not: 0b100,
    rejects: 0b1000,
    resolves: 0b10000,
    silent: 0b100000,
};
const LABEL_EXPECTED = "Expected:";
const LABEL_RECEIVED = "Received:";
/** @type {CaseEventType[]} */
const CASE_EVENT_LOG_COLORS = ["assertion", "query", "step", "time"];
const MAX_STACK_LENGTH = 10;

/** @type {WeakMap<any, any>} */
const debugLabelCache = new WeakMap();
/** @type {Set<Matcher>} */
const unconsumedMatchers = new Set();

let currentStack = "";

/**
 * @param {ExpectBuilderParams} params
 * @returns {[typeof enrichedExpect, typeof expectHooks]}
 */
export function makeExpect(params) {
    /**
     * @param {AfterTestOptions} [options]
     */
    function afterTest(options) {
        const { test } = currentResult;

        removeInteractionListener?.();

        currentResult.done();

        const {
            assertion: assertionCount = 0,
            error: errorCount = 0,
            query: queryCount = 0,
        } = currentResult.counts;

        if (unconsumedMatchers.size) {
            let times;
            switch (unconsumedMatchers.size) {
                case 1:
                    times = [r`once`];
                    break;
                case 2:
                    times = [r`twice`];
                    break;
                default:
                    times = [unconsumedMatchers.size, r`times`];
            }
            currentResult.registerEvent("assertion", {
                label: "expect",
                pass: false,
                reportMessage: [r`called`, ...times, r`without calling any matchers`],
            });
            unconsumedMatchers.clear();
        }

        if (currentResult.currentSteps.length) {
            currentResult.registerEvent("assertion", {
                label: "step",
                docLabel: "expect.step",
                pass: false,
                failedDetails: detailsFromEntries([
                    ["Steps:", currentResult.currentSteps],
                ]),
                reportMessage: [r`unverified steps`],
            });
        }

        if (!(assertionCount + queryCount)) {
            currentResult.registerEvent("assertion", {
                label: "assertions",
                docLabel: "expect.assertions",
                pass: false,
                reportMessage: [
                    r`expected at least`,
                    1,
                    r`assertion or query event, but none were run`,
                ],
            });
        } else if (
            currentResult.expectedAssertions &&
            currentResult.expectedAssertions !== assertionCount
        ) {
            currentResult.registerEvent("assertion", {
                label: "assertions",
                docLabel: "expect.assertions",
                pass: false,
                reportMessage: [
                    r`expected`,
                    currentResult.expectedAssertions,
                    r`assertions, but`,
                    assertionCount,
                    r`were run`,
                ],
            });
        }

        if (currentResult.currentErrors.length) {
            currentResult.registerEvent("assertion", {
                label: "errors",
                docLabel: "expect.errors",
                pass: false,
                reportMessage: [
                    currentResult.currentErrors.length,
                    r`unverified error(s)`,
                ],
            });
        }

        if (
            currentResult.expectedErrors &&
            currentResult.expectedErrors !== errorCount
        ) {
            currentResult.registerEvent("assertion", {
                label: "errors",
                docLabel: "expect.errors",
                pass: false,
                reportMessage: [
                    r`expected`,
                    currentResult.expectedErrors,
                    r`errors, but`,
                    errorCount,
                    r`were thrown`,
                ],
            });
        }

        if (test?.config.todo) {
            if (currentResult.pass) {
                currentResult.registerEvent("assertion", {
                    label: "TODO",
                    pass: false,
                    reportMessage: [
                        r`all assertions passed: remove "todo" test modifier`,
                    ],
                });
            } else {
                currentResult.pass = true;
            }
        }

        if (options?.aborted) {
            currentResult.registerEvent("assertion", {
                label: "aborted",
                pass: false,
                reportMessage: [r`test was aborted, results may not be relevant`],
            });
        }

        if (test) {
            if (options?.aborted) {
                test.status = Test.ABORTED;
            } else if (currentResult.pass) {
                test.status ||= Test.PASSED;
            } else {
                test.status = Test.FAILED;
            }

            /** @type {import("../hoot_utils").Reporting} */
            const report = {
                assertions: assertionCount,
                duration: test.lastResults?.duration || 0,
                tests: 1,
            };
            if (!currentResult.pass) {
                report.failed = 1;
            } else if (test.config.todo) {
                report.todo = 1;
            } else {
                report.passed = 1;
            }

            test.parent?.reporting.add(report);
        }

        const result = currentResult;
        if (!options?.debug) {
            currentResult = null;
            currentResultInErrorState = false;
        }

        return result;
    }

    /**
     * @param {number} expected
     */
    function assertions(expected) {
        if (!currentResult) {
            throw scopeError("expect.assertions");
        }
        ensureArguments(arguments, "integer");
        if (expected < 1) {
            throw new HootError(`expected assertions count should be more than 1`);
        }

        currentResult.expectedAssertions = expected;
    }

    /**
     * @param {Test} test
     */
    function beforeTest(test) {
        if (test) {
            test.results.push(new CaseResult(test, params.headless));

            currentResult = test.results.at(-1);
        } else {
            currentResult = new CaseResult(null, params.headless);
        }
        currentResultInErrorState = false;
        const listenedEvents = ["query"];
        if (!params.headless) {
            listenedEvents.push("interaction", "server", "time");
        }
        removeInteractionListener = addInteractionListener(
            listenedEvents,
            onInteraction,
        );
    }

    /**
     * @param {{ errors: unknown[]; options: VerifierOptions }} resolver
     * @param {boolean} forceCheck
     */
    function checkErrors(resolver, forceCheck) {
        if (!resolver) {
            return false;
        }
        const { errors, options } = resolver;
        const { currentErrors } = currentResult;
        const pass =
            currentErrors.length === errors.length &&
            currentErrors.every(
                (error, i) =>
                    match(error, errors[i]) ||
                    (error.cause && match(error.cause, errors[i])),
            );

        if (pass || forceCheck) {
            currentResult.consumeErrors();

            const reportMessage = pass
                ? errors.length
                    ? listJoin(errors, ARROW_RIGHT)
                    : "no errors"
                : "expected the following errors";
            const assertion = {
                label: "verifyErrors",
                docLabel: "expect.verifyErrors",
                message: options?.message,
                pass,
                reportMessage,
            };
            if (!pass) {
                const fActual = currentErrors.map(formatError);
                const fExpected = errors.map(formatError);
                assertion.failedDetails = detailsFromValuesWithDiff(fExpected, fActual);
                assertion.stack = getStack(1);
            }
            currentResult.registerEvent("assertion", assertion);
        }

        return pass;
    }

    /**
     * @param {{ steps: unknown[]; options: VerifierOptions } | null} resolver
     * @param {boolean} forceCheck
     */
    function checkSteps(resolver, forceCheck) {
        if (!resolver) {
            return false;
        }
        const { steps, options } = resolver;
        const receivedSteps = currentResult.currentSteps;
        const pass = deepEqual(steps, receivedSteps, options);

        if (pass || forceCheck) {
            currentResult.consumeSteps();

            const separator = options?.ignoreOrder ? AMPERSAND : ARROW_RIGHT;
            const reportMessage = pass
                ? receivedSteps.length
                    ? listJoin(receivedSteps, separator)
                    : "no steps"
                : "expected the following steps";
            const assertion = {
                label: "verifySteps",
                docLabel: "expect.verifySteps",
                message: options?.message,
                pass,
                reportMessage,
            };
            if (!pass) {
                assertion.failedDetails = detailsFromValuesWithDiff(
                    steps,
                    receivedSteps,
                );
                assertion.stack = getStack(1);
            }
            currentResult.registerEvent("assertion", assertion);
        }

        return pass;
    }

    /**
     * @param {number} expected
     */
    function errors(expected) {
        if (!currentResult) {
            throw scopeError("expect.errors");
        }
        ensureArguments(arguments, "integer");

        currentResult.expectedErrors = expected;
    }

    /**
     * @param {Error} error
     * @returns {boolean}
     */
    function onError(error) {
        if (!currentResult) {
            return false;
        }

        currentResult.registerEvent("error", error);
        currentResultInErrorState =
            currentResult.expectedErrors < (currentResult.counts.error || 0);

        checkErrors(currentResult.errorResolver, false);

        return !currentResultInErrorState;
    }

    /**
     * @param {CustomEvent<InteractionDetails>} event
     */
    function onInteraction({ detail, type }) {
        if (!currentResult) {
            return;
        }

        currentResult.registerEvent(type, detail);
    }

    /**
     * @param {unknown} value
     */
    function step(value) {
        if (!currentResult) {
            throw scopeError("expect.step");
        }

        currentResult.registerEvent("step", value);

        checkSteps(currentResult.stepResolver, false);
    }

    /**
     * @param {unknown[]} errors
     * @param {VerifierOptions} [options]
     * @returns {boolean}
     */
    function verifyErrors(errors, options) {
        if (!currentResult) {
            throw scopeError("expect.verifyErrors");
        }
        ensureArguments(arguments, "any[]", ["object", null]);
        if (errors.length > currentResult.expectedErrors) {
            throw new HootError(
                `cannot call \`expect.verifyErrors()\` without calling \`expect.errors()\` beforehand`,
            );
        }

        return checkErrors({ errors, options }, true);
    }

    /**
     * @param {unknown[]} steps
     * @param {VerifierOptions} [options]
     * @returns {boolean}
     */
    function verifySteps(steps, options) {
        if (!currentResult) {
            throw scopeError("expect.verifySteps");
        }
        ensureArguments(arguments, "any[]", ["object", null]);

        return checkSteps({ steps, options }, true);
    }

    /**
     * @param {unknown[]} errors
     * @param {AsyncVerifierOptions} [options]
     * @returns {Promise<boolean>}
     */
    function waitForErrors(errors, options) {
        if (!currentResult) {
            throw scopeError("expect.waitForErrors");
        }
        ensureArguments(arguments, "any[]", ["object", null]);

        checkErrors(currentResult.errorResolver, true);

        if (checkErrors({ errors, options }, false)) {
            return true;
        }

        currentResult.errorResolver = {
            ...Promise.withResolvers(),
            errors,
            options,
            timeout: setTimeout(
                () => checkErrors(currentResult.errorResolver, true),
                options?.timeout ?? 2000,
            ),
        };
        return currentResult.errorResolver.promise;
    }

    /**
     * @param {unknown[]} steps
     * @param {AsyncVerifierOptions} [options]
     * @returns {Promise<boolean>}
     */
    async function waitForSteps(steps, options) {
        if (!currentResult) {
            throw scopeError("expect.waitForSteps");
        }
        ensureArguments(arguments, "any[]", ["object", null]);

        checkSteps(currentResult.stepResolver, true);

        if (checkSteps({ steps, options }, false)) {
            return true;
        }

        currentResult.stepResolver = {
            ...Promise.withResolvers(),
            steps,
            options,
            timeout: setTimeout(
                () => checkSteps(currentResult.stepResolver, true),
                options?.timeout ?? 2000,
            ),
        };
        return currentResult.stepResolver.promise;
    }

    /**
     * @template [R=unknown]
     * @param {R} received
     */
    function expect(received) {
        if (arguments.length > 1) {
            throw new HootError(`\`expect()\` only accepts a single argument`);
        }

        if (!currentResult) {
            throw scopeError("expect");
        }

        let flags = 0;
        if (currentResultInErrorState) {
            flags |= FLAGS.error;
        }
        if (params.headless) {
            flags |= FLAGS.headless;
        }

        return new Matcher(currentResult, received, flags);
    }

    const enrichedExpect = $assign(expect, {
        assertions,
        errors,
        step,
        verifyErrors,
        verifySteps,
        waitForErrors,
        waitForSteps,
    });
    const expectHooks = {
        after: afterTest,
        before: beforeTest,
        error: onError,
    };

    /** @type {CaseResult | null} */
    let currentResult = null;
    let currentResultInErrorState = false;

    let removeInteractionListener;

    return [enrichedExpect, expectHooks];
}

export class CaseResult {
    duration = 0;
    pass = true;
    /** @type {Test | null} */
    test = null;
    ts = $floor($now());

    /** @type {CaseEvent[]} */
    events = [];
    /** @type {Partial<Record<CaseEventType, number>>} */
    counts = $create(null);

    expectedAssertions = 0;
    expectedErrors = 0;

    currentErrors = [];
    currentSteps = [];
    /** @type {AsyncResolver<{ errors: unknown[] }> | null} */
    errorResolver = null;
    /** @type {AsyncResolver<{ steps: unknown[] }> | null} */
    stepResolver = null;

    /**
     * @param {Test | null} [test]
     * @param {boolean} [headless]
     */
    constructor(test, headless) {
        if (test) {
            this.test = test;
        }

        this.headless = !!headless;

        markRaw(this);
    }

    consumeErrors() {
        if (this.errorResolver) {
            clearTimeout(this.errorResolver.timeout);
            this.errorResolver.resolve(true);
            this.errorResolver = null;
        }
        this.currentErrors = [];
    }

    consumeSteps() {
        if (this.stepResolver) {
            clearTimeout(this.stepResolver.timeout);
            this.stepResolver.resolve(true);
            this.stepResolver = null;
        }
        this.currentSteps = [];
    }

    /**
     * @param {CaseEventType} type
     */
    getEvents(type) {
        const nType = typeof type === "number" ? type : CASE_EVENT_TYPES[type].value;
        return this.events.filter((event) => event.type & nType);
    }

    done() {
        this.duration = $floor($now()) - this.ts;
    }

    /**
     * @param {CaseEventType} type
     * @param {unknown} value
     */
    registerEvent(type, value) {
        let caseEvent;
        this.counts[type] ||= 0;
        this.counts[type]++;
        switch (type) {
            case "assertion": {
                if (value && this.headless) {
                    delete value.docLabel;
                }
                caseEvent = new Assertion(this.counts.assertion, value);
                this.pass &&= caseEvent.pass;
                break;
            }
            case "error": {
                caseEvent = new CaseError(value);
                this.currentErrors.push(value);
                break;
            }
            case "step": {
                if (!this.headless) {
                    caseEvent = new Step(value);
                }
                this.currentSteps.push(deepCopy(value));
                break;
            }
            default: {
                if (!this.headless || type === "query") {
                    caseEvent = new DOMCaseEvent(type, value);
                }
                break;
            }
        }
        if (caseEvent) {
            if (logger.canLog("debug") && CASE_EVENT_LOG_COLORS.includes(type)) {
                const colorName =
                    caseEvent.pass === false ? "rose" : CASE_EVENT_TYPES[type].color;
                const logArgs = [[caseEvent.label, getColorHex(colorName)]];
                for (const part of caseEvent.message) {
                    if (isLabel(part)) {
                        logArgs.push(debugLabelCache.get(part) ?? part[0]);
                        debugLabelCache.delete(part);
                    } else {
                        logArgs.push(part);
                    }
                }
                if (caseEvent.additionalMessage) {
                    logArgs.push("\n", { message: caseEvent.additionalMessage });
                }
                logger.logTestEvent(...logArgs);
            }
            this.events.push(caseEvent);
        }
    }
}

/**
 * @template R
 * @template [A=R]
 * @template [Async=false]
 */
export class Matcher {
    /**
     * @private
     * @type {number}
     */
    _flags = 0;
    /**
     * @private
     * @type {R}
     */
    _received = null;
    /**
     * @private
     * @type {CaseResult}
     */
    _result;

    /**
     * @param {CaseResult} result
     * @param {R} received
     * @param {number} flags
     */
    constructor(result, received, flags) {
        this._flags = flags;
        this._result = result;
        this._received = received;

        unconsumedMatchers.add(this);
    }

    /**
     * @returns {Omit<Matcher<R, A, Async>, "not">}
     */
    get not() {
        if (this._flags & FLAGS.not) {
            throw matcherModifierError("not", `matcher is already negated`);
        }
        return this._clone(FLAGS.not);
    }

    /**
     * @returns {Omit<Matcher<R, A, true>, "rejects" | "resolves">}
     */
    get rejects() {
        if (this._flags & (FLAGS.rejects | FLAGS.resolves)) {
            throw matcherModifierError(
                "rejects",
                `matcher value has already been wrapped in a promise resolver`,
            );
        }
        return this._clone(FLAGS.rejects);
    }

    /**
     * @returns {Omit<Matcher<R, A, true>, "rejects" | "resolves">}
     */
    get resolves() {
        if (this._flags & (FLAGS.rejects | FLAGS.resolves)) {
            throw matcherModifierError(
                "resolves",
                `matcher value has already been wrapped in a promise resolver`,
            );
        }
        return this._clone(FLAGS.resolves);
    }

    /**
     * @param {R} expected
     * @param {ExpectOptions} [options]
     */
    toBe(expected, options) {
        this._ensureArguments(arguments, "any");

        return this._resolve(() => ({
            name: "toBe",
            acceptedType: "any",
            predicate: (received) => strictEqual(expected, received),
            message: options?.message,
            onPass: () => [
                r`received value is[! not] strictly equal to`,
                this._received,
            ],
            onFail: () => [r`expected values to be strictly equal`],
            getFailedDetails: (received) =>
                detailsFromValuesWithDiff(expected, received),
        }));
    }

    /**
     * @param {R} expected
     * @param {ExpectOptions & { margin?: number }} [options]
     */
    toBeCloseTo(expected, options) {
        this._ensureArguments(arguments, "number");

        const margin = options?.margin ?? 1;
        return this._resolve(() => ({
            name: "toBeCloseTo",
            acceptedType: "number",
            predicate: (received) => $abs(expected - received) < margin,
            message: options?.message,
            onPass: () => [r`received value is[! not] close to`, this._received],
            onFail: () => [r`expected values to be close to the given value`],
            getFailedDetails: (received) =>
                detailsFromValuesWithDiff(expected, received),
        }));
    }

    /**
     * @param {ExpectOptions} [options]
     */
    toBeEmpty(options) {
        this._ensureArguments(arguments);

        return this._resolve(() => ({
            name: "toBeEmpty",
            acceptedType: ["any"],
            predicate: (received) => isEmpty(received),
            message: options?.message,
            onPass: () => [this._received, r`should[! not] be empty`],
            onFail: () => [this._received, r`is[! not] empty`],
            getFailedDetails: detailsFromValues,
        }));
    }

    /**
     * @param {number} min
     * @param {ExpectOptions} [options]
     */
    toBeGreaterThan(min, options) {
        this._ensureArguments(arguments, "number");

        return this._resolve(() => ({
            name: "toBeGreaterThan",
            acceptedType: "number",
            predicate: (received) => min < received,
            message: options?.message,
            onPass: () => [this._received, r`is[! not] strictly greater than`, min],
            onFail: () => [r`expected value[! not] to be strictly greater`],
            getFailedDetails: (received) =>
                detailsFromEntries([
                    ["Minimum:", min],
                    [null, received],
                ]),
        }));
    }

    /**
     * @param {Function} cls
     * @param {ExpectOptions} [options]
     */
    toBeInstanceOf(cls, options) {
        this._ensureArguments(arguments, "function");

        return this._resolve(() => ({
            name: "toBeInstanceOf",
            acceptedType: "any",
            predicate: (received) => isInstanceOf(received, cls),
            message: options?.message,
            onPass: () => [this._received, r`is[! not] an instance of`, cls],
            onFail: () => [
                r`expected value[! not] to be an instance of the given class`,
            ],
            getFailedDetails: (received) =>
                detailsFromEntries([
                    [null, cls],
                    ["Actual parent class:", getConstructor(received).name],
                ]),
        }));
    }

    /**
     * @param {number} max
     * @param {ExpectOptions} [options]
     */
    toBeLessThan(max, options) {
        this._ensureArguments(arguments, "number");

        return this._resolve(() => ({
            name: "toBeLessThan",
            acceptedType: "number",
            predicate: (received) => received < max,
            message: options?.message,
            onPass: () => [this._received, r`is[! not] strictly less than`, max],
            onFail: () => [r`expected value[! not] to be strictly less`],
            getFailedDetails: (received) =>
                detailsFromEntries([
                    ["Maximum:", max],
                    [null, received],
                ]),
        }));
    }

    /**
     * @param {number} min
     * @param {ExpectOptions} [options]
     */
    toBeGreaterThanOrEqual(min, options) {
        this._ensureArguments(arguments, "number");

        return this._resolve(() => ({
            name: "toBeGreaterThanOrEqual",
            acceptedType: "number",
            predicate: (received) => min <= received,
            message: options?.message,
            onPass: () => [this._received, r`is[! not] greater than or equal to`, min],
            onFail: () => [r`expected value[! not] to be greater than or equal to`],
            getFailedDetails: (received) =>
                detailsFromEntries([
                    ["Minimum:", min],
                    [null, received],
                ]),
        }));
    }

    /**
     * @param {number} max
     * @param {ExpectOptions} [options]
     */
    toBeLessThanOrEqual(max, options) {
        this._ensureArguments(arguments, "number");

        return this._resolve(() => ({
            name: "toBeLessThanOrEqual",
            acceptedType: "number",
            predicate: (received) => received <= max,
            message: options?.message,
            onPass: () => [this._received, r`is[! not] less than or equal to`, max],
            onFail: () => [r`expected value[! not] to be less than or equal to`],
            getFailedDetails: (received) =>
                detailsFromEntries([
                    ["Maximum:", max],
                    [null, received],
                ]),
        }));
    }

    /**
     * @param {ArgumentType} type
     * @param {ExpectOptions} [options]
     */
    toBeOfType(type, options) {
        this._ensureArguments(arguments, "string");

        return this._resolve(() => ({
            name: "toBeOfType",
            acceptedType: "any",
            predicate: (received) => isOfType(received, type),
            message: options?.message,
            onPass: () => [this._received, r`is[! not] of type`, type],
            onFail: () => [r`expected value to be of the given type`],
            getFailedDetails: (received) =>
                detailsFromEntries([
                    ["Expected type:", type],
                    ["Received value:", received],
                ]),
        }));
    }

    /**
     * @param {number} min
     * @param {number} max
     * @param {ExpectOptions} [options]
     */
    toBeWithin(min, max, options) {
        this._ensureArguments(arguments, "number", "number");

        if (min > max) {
            [min, max] = [max, min];
        }
        if (min === max) {
            throw new HootError(
                `min and max cannot be equal (did you mean to use \`toBe()\`?)`,
            );
        }

        return this._resolve(() => ({
            name: "toBeWithin",
            acceptedType: "number",
            predicate: (received) => min <= received && received <= max,
            message: options?.message,
            onPass: () => [this._received, r`is[! not] between`, min, r`and`, max],
            onFail: () => [r`expected value[! not] to be between given range`],
            getFailedDetails: (received) =>
                detailsFromValues(`${min} - ${max}`, received),
        }));
    }

    /**
     * @param {R} expected
     * @param {ExpectOptions & DeepEqualOptions} [options]
     */
    toEqual(expected, options) {
        this._ensureArguments(arguments, "any");

        return this._resolve(() => ({
            name: "toEqual",
            acceptedType: "any",
            predicate: (received) => deepEqual(expected, received, options),
            message: options?.message,
            onPass: () => [r`received value is[! not] deeply equal to`, this._received],
            onFail: () => [r`expected values to[! not] be deeply equal`],
            getFailedDetails: (received) =>
                detailsFromValuesWithDiff(expected, received),
        }));
    }

    /**
     * @param {number} length
     * @param {ExpectOptions} [options]
     */
    toHaveLength(length, options) {
        this._ensureArguments(arguments, "integer");

        return this._resolve(() => {
            const receivedLength = getLength(this._received);
            return {
                name: "toHaveLength",
                acceptedType: ["string", "array", "object"],
                predicate: () => strictEqual(receivedLength, length),
                message: options?.message,
                onPass: () => [this._received, r`has[! not] a length of`, length],
                onFail: () => [r`expected value[! not] to have the given length`],
                getFailedDetails: () =>
                    detailsFromEntries([
                        ["Expected length:", length],
                        [null, receivedLength],
                    ]),
            };
        });
    }

    /**
     * @param {keyof R | R[number]} item
     * @param {ExpectOptions} [options]
     */
    toInclude(item, options) {
        this._ensureArguments(arguments, "any");

        return this._resolve(() => ({
            name: "toInclude",
            acceptedType: ["string", "any[]", "object"],
            predicate: (received) => includes(received, item),
            message: options?.message,
            onPass: () => [this._received, r`[includes!does not include]`, item],
            onFail: () => [r`expected object[! not] to include the given item`],
            getFailedDetails: (received) =>
                detailsFromEntries([
                    ["Item:", item],
                    ["Object:", received],
                ]),
        }));
    }

    /**
     * @param {import("../hoot_utils").Matcher} matcher
     * @param {ExpectOptions} [options]
     */
    toMatch(matcher, options) {
        this._ensureArguments(arguments, "any");

        return this._resolve(() => ({
            name: "toMatch",
            acceptedType: "any",
            predicate: (received) => match(received, matcher),
            message: options?.message,
            onPass: () => [this._received, r`[matches!does not match]`, matcher],
            onFail: () => [r`expected value[! not] to match the given matcher`],
            getFailedDetails: (received) =>
                detailsFromEntries([
                    ["Matcher:", matcher],
                    [null, received],
                ]),
        }));
    }

    /**
     * @param {Partial<R>} partialObject
     * @param {ExpectOptions} [options]
     */
    toMatchObject(partialObject, options) {
        this._ensureArguments(arguments, "object");

        return this._resolve(() => ({
            name: "toMatchObject",
            acceptedType: ["object"],
            predicate: (received) =>
                deepEqual(received, partialObject, { partial: true }),
            message: options?.message,
            onPass: () => [
                this._received,
                r`[matches!does not match] object`,
                partialObject,
            ],
            onFail: () => [r`expected object[! not] to match the given shape`],
            getFailedDetails: (received) =>
                detailsFromEntries([
                    ["Partial object:", partialObject],
                    ["Object:", received],
                ]),
        }));
    }

    /**
     * @param {import("../hoot_utils").Matcher} [matcher=Error]
     * @param {ExpectOptions} [options]
     */
    toThrow(matcher = Error, options) {
        this._ensureArguments(arguments, "any");

        return this._resolve(() => {
            const isAsync = this._flags & (FLAGS.rejects | FLAGS.resolves);
            let returnValue;
            if (isAsync) {
                returnValue = this._received;
            } else {
                try {
                    returnValue = this._received();
                } catch (error) {
                    returnValue = error;
                }
            }
            return {
                name: "toThrow",
                acceptedType: ["function", "error"],
                predicate: () => match(returnValue, matcher),
                message: options?.message,
                onPass: () => [
                    this._received,
                    r`did[! not] ${isAsync ? "reject" : "throw"} a matching value`,
                ],
                onFail: () => [
                    this._received,
                    r`${
                        isAsync ? "rejected" : "threw"
                    } a value that did not match the given matcher`,
                ],
                getFailedDetails: () =>
                    detailsFromEntries([
                        ["Matcher:", matcher],
                        [null, returnValue],
                    ]),
            };
        });
    }

    /**
     * @param {ExpectOptions & { indeterminate?: boolean }} [options]
     */
    toBeChecked(options) {
        this._ensureArguments(arguments);

        const prop = options?.indeterminate ? "indeterminate" : "checked";
        const pseudo = ":" + prop;

        return this._resolve(() => ({
            name: "toBeChecked",
            acceptedType: ["string", "node", "node[]"],
            mapElements: (el) => el.matches?.(pseudo),
            predicate: (checked) => !!checked,
            message: options?.message,
            onPass: () => [this._received, r`[is%are][! not] ${prop}`],
            onFail: () => [r`expected`, this._received, r`[! not] to be ${prop}`],
            getFailedDetails: (checked) => detailsFromEntries([["Checked:", checked]]),
        }));
    }

    /**
     * @param {ExpectOptions} [options]
     */
    toBeDisplayed(options) {
        this._ensureArguments(arguments);

        return this._resolve(() => ({
            name: "toBeDisplayed",
            acceptedType: ["string", "node", "node[]"],
            mapElements: isNodeDisplayed,
            predicate: (displayed) => !!displayed,
            message: options?.message,
            onPass: () => [this._received, r`[is%are][! not] displayed`],
            onFail: () => [r`expected`, this._received, r`[! not] to be displayed`],
            getFailedDetails: (displayed) =>
                detailsFromEntries([["Displayed:", displayed]]),
        }));
    }

    /**
     * @param {ExpectOptions} [options]
     */
    toBeEnabled(options) {
        this._ensureArguments(arguments);

        return this._resolve(() => ({
            name: "toBeEnabled",
            acceptedType: ["string", "node", "node[]"],
            mapElements: (el) => el.matches?.(":enabled"),
            predicate: (enabled) => !!enabled,
            message: options?.message,
            onPass: () => [this._received, r`[is%are] [enabled!disabled]`],
            onFail: () => [r`expected`, this._received, r`to be [enabled!disabled]`],
            getFailedDetails: (enabled) => detailsFromEntries([["Enabled:", enabled]]),
        }));
    }

    /**
     * @param {ExpectOptions} [options]
     */
    toBeFocused(options) {
        this._ensureArguments(arguments);

        return this._resolve(() => ({
            name: "toBeFocused",
            acceptedType: ["string", "node", "node[]"],
            mapElements: (el) => getActiveElement(el),
            predicate: (activeEl, el) => strictEqual(el, activeEl),
            message: options?.message,
            onPass: () => [this._received, r`[is%are][! not] focused`],
            onFail: () => [this._received, r`should[! not] be focused`],
            getFailedDetails: (focused) => detailsFromEntries([["Focused:", focused]]),
        }));
    }

    /**
     * @param {ExpectOptions} [options]
     */
    toBeVisible(options) {
        this._ensureArguments(arguments);

        return this._resolve(() => ({
            name: "toBeVisible",
            acceptedType: ["string", "node", "node[]"],
            mapElements: isNodeVisible,
            predicate: (visible) => !!visible,
            message: options?.message,
            onPass: () => [this._received, r`[is%are] [visible!hidden]`],
            onFail: () => [r`expected`, this._received, r`to be [visible!hidden]`],
            getFailedDetails: (visible) => detailsFromEntries([["Visible:", visible]]),
        }));
    }

    /**
     * @param {string} attribute
     * @param {import("../hoot_utils").Matcher} [value]
     * @param {ExpectOptions} [options]
     */
    toHaveAttribute(attribute, value, options) {
        this._ensureArguments(arguments, "string", ["string", "number", "regex", null]);

        const expectsValue = !isNil(value);

        return this._resolve(() => ({
            name: "toHaveAttribute",
            acceptedType: ["string", "node", "node[]"],
            mapElements: (el) => getNodeAttribute(el, attribute),
            predicate: (elAttr, el) =>
                expectsValue ? valueMatches(elAttr, value) : el.hasAttribute(attribute),
            message: options?.message,
            onPass: () => [
                r`attribute`,
                attribute,
                r`on`,
                this._received,
                ...(expectsValue
                    ? [r`[matches!does not match]`, value]
                    : [r`is[! not] set`]),
            ],
            onFail: () => [
                this._received,
                r`[does%do] not have the correct attribute${expectsValue ? " value" : ""}`,
            ],
            getFailedDetails: (elAttr) =>
                detailsFromValuesWithDiff(expectsValue ? value : attribute, elAttr),
        }));
    }

    /**
     * @param {string | string[]} className
     * @param {ExpectOptions & ClassListOptions} [options]
     */
    toHaveClass(className, options) {
        this._ensureArguments(arguments, ["string", "string[]"]);

        const rawClassNames = ensureArray(className);
        const classNames = rawClassNames.flatMap((cls) =>
            cls.trim().split(R_WHITE_SPACE),
        );

        return this._resolve(() => ({
            name: "toHaveClass",
            acceptedType: ["string", "node", "node[]"],
            mapElements: (el) => [...el.classList].sort(),
            predicate: (classes) =>
                options?.exact
                    ? deepEqual(classNames, classes, { ignoreOrder: true })
                    : classNames.every((cls) => classes.includes(cls)),
            message: options?.message,
            onPass: () => [
                this._received,
                r`[[has%have]![does%do] not have] class${classNames.length === 1 ? "" : "es"}`,
                ...listJoin(classNames, ",", "and"),
            ],
            onFail: () => [
                r`expected`,
                this._received,
                r`[to have all!not to have any] of the given class names`,
            ],
            getFailedDetails: (classes) =>
                detailsFromValues(classNames.join(" "), classes.join(" ")),
        }));
    }

    /**
     * @param {number} [amount]
     * @param {ExpectOptions} [options]
     */
    toHaveCount(amount, options) {
        this._ensureArguments(arguments, ["integer", null]);

        const anyAmount = isNil(amount);
        return this._resolve(() => {
            const elMap = new ElementMap(this._received);
            return {
                name: "toHaveCount",
                acceptedType: ["string", "node", "node[]"],
                predicate: () =>
                    anyAmount ? elMap.size > 0 : strictEqual(elMap.size, amount),
                message: options?.message,
                onPass: () => [r`found`, elMap],
                onFail: () => [
                    r`found`,
                    elMap,
                    ...(anyAmount ? [r`and expected [any amount!none]`] : []),
                ],
                getFailedDetails: () => [
                    ...detailsFromValues(
                        anyAmount ? (this._flags & FLAGS.not ? S_NONE : S_ANY) : amount,
                        elMap.size,
                    ),
                    Markup.text("Elements:", [...elMap.keys()]),
                ],
            };
        });
    }

    /**
     * @param {string | RegExp} [expected]
     * @param {ExpectOptions & FormatXmlOptions} [options]
     */
    toHaveInnerHTML(expected, options) {
        this._ensureArguments(arguments, ["string", "regex"]);

        return this._toHaveHTML("toHaveInnerHTML", "innerHTML", ...arguments);
    }

    /**
     * @param {string | RegExp} [expected]
     * @param {ExpectOptions & FormatXmlOptions} [options]
     */
    toHaveOuterHTML(expected, options) {
        this._ensureArguments(arguments, ["string", "regex"]);

        return this._toHaveHTML("toHaveOuterHTML", "outerHTML", ...arguments);
    }

    /**
     * @param {string} property
     * @param {any} [value]
     * @param {ExpectOptions} [options]
     */
    toHaveProperty(property, value, options) {
        this._ensureArguments(arguments, "string", "any");

        const expectsValue = !isNil(value);
        return this._resolve(() => ({
            name: "toHaveProperty",
            acceptedType: ["string", "node", "node[]"],
            mapElements: (el) => el[property],
            predicate: (elProp, el) =>
                expectsValue ? valueMatches(elProp, value) : property in el,
            message: options?.message,
            onPass: () => [
                r`property`,
                property,
                r`on`,
                this._received,
                ...(expectsValue
                    ? [r`[matches!does not match]`, value]
                    : [r`is[! not] set`]),
            ],
            onFail: () => [
                this._received,
                r`[does%do] not have the correct property${expectsValue ? " value" : ""}`,
            ],
            getFailedDetails: (elProp) =>
                detailsFromValuesWithDiff(expectsValue ? value : property, elProp),
        }));
    }

    /**
     * @param {Partial<DOMRect> | Target} rect
     * @param {ExpectOptions & QueryRectOptions} [options]
     */
    toHaveRect(rect, options) {
        this._ensureArguments(arguments, ["object", "string", "node", "node[]"]);

        let refRect;
        if (typeof rect === "string" || isNode(rect)) {
            refRect = { ...queryRect(rect, options) };
        } else {
            refRect = rect;
        }

        const entries = $entries(refRect);

        return this._resolve(() => ({
            name: "toHaveRect",
            acceptedType: ["string", "node", "node[]"],
            mapElements: (el) => getNodeRect(el, options),
            predicate: (elRect) =>
                entries.every(([key, val]) => strictEqual(elRect[key], val)),
            message: options?.message,
            onPass: () => [
                this._received,
                r`[has%have] the expected DOM rect of`,
                rect,
            ],
            onFail: () => [r`expected`, this._received, r`to have the given DOM rect`],
            getFailedDetails: (elRect) => detailsFromValuesWithDiff(rect, elRect),
        }));
    }

    /**
     * @param {string | Record<string, string | RegExp>} style
     * @param {ExpectOptions & DOMStyleOptions} [options]
     */
    toHaveStyle(style, options) {
        this._ensureArguments(arguments, ["string", "object"]);

        const styleDef = parseInlineStyle(style, S_ANY);
        const styleKeys = $keys(styleDef);

        return this._resolve(() => ({
            name: "toHaveStyle",
            acceptedType: ["string", "node", "node[]"],
            mapElements: (el) =>
                options?.inline
                    ? parseInlineStyle(el.getAttribute("style"))
                    : getStyleValues(el, $keys(styleDef)),
            predicate: (elStyle) =>
                styleKeys.every((key) => valueMatches(elStyle[key], styleDef[key])) &&
                (!options?.exact ||
                    deepEqual(styleKeys, $keys(elStyle), { ignoreOrder: true })),
            message: options?.message,
            onPass: () => [
                this._received,
                r`[has%have] the expected style values for`,
                ...listJoin($keys(styleDef), ",", "and"),
            ],
            onFail: () => [
                r`expected`,
                this._received,
                r`[to have all!not to have any] of the given style properties`,
            ],
            getFailedDetails: (elStyle) => detailsFromValuesWithDiff(styleDef, elStyle),
        }));
    }

    /**
     * @param {string | RegExp} [text]
     * @param {ExpectOptions & QueryTextOptions} [options]
     */
    toHaveText(text, options) {
        this._ensureArguments(arguments, ["string", "regex", null]);

        const expectsText = !isNil(text);

        return this._resolve(() => ({
            name: "toHaveText",
            acceptedType: ["string", "node", "node[]"],
            mapElements: (el) => getNodeText(el, options),
            predicate: (elText) =>
                expectsText ? valueMatches(elText, text) : elText.length > 0,
            message: options?.message,
            onPass: () => [
                this._received,
                r`[[has%have]![does%do] not have] text`,
                text,
            ],
            onFail: () => [
                r`expected`,
                this._received,
                r`[! not] to have the given text`,
            ],
            getFailedDetails: (elText) => detailsFromValuesWithDiff(text, elText),
        }));
    }

    /**
     * @param {ReturnType<typeof getNodeValue> | RegExp} [value]
     * @param {ExpectOptions & { raw?: boolean }} [options]
     */
    toHaveValue(value, options) {
        this._ensureArguments(arguments, [
            "string",
            "string[]",
            "number",
            "object[]",
            "regex",
            null,
        ]);

        const expectsValue = !isNil(value);

        return this._resolve(() => ({
            name: "toHaveValue",
            acceptedType: ["string", "node", "node[]"],
            mapElements: (el) => getNodeValue(el, options?.raw),
            predicate: (elValue, el) => {
                if (isCheckable(el)) {
                    throw new HootError(
                        `cannot call \`toHaveValue()\` on a checkbox or radio input: use \`toBeChecked()\` instead`,
                    );
                }
                if (!expectsValue) {
                    return isIterable(elValue)
                        ? [...elValue].length > 0
                        : el.value !== "";
                }
                if (isIterable(elValue)) {
                    if (isIterable(value)) {
                        return deepEqual(elValue, value);
                    }
                    elValue = el.value;
                }
                return valueMatches(elValue, value);
            },
            message: options?.message,
            onPass: () => [
                this._received,
                r`[[has%have]![does%do] not have] value`,
                value,
            ],
            onFail: () => [
                r`expected`,
                this._received,
                r`[! not] to have the given value`,
            ],
            getFailedDetails: (elValue) => detailsFromValuesWithDiff(value, elValue),
        }));
    }

    /**
     * @private
     * @param {number} flags
     */
    _clone(flags) {
        unconsumedMatchers.delete(this);
        return new this.constructor(this._result, this._received, this._flags | flags);
    }

    /**
     * @private
     * @param {any[]} argumentsObject
     * @param {...(ArgumentType | ArgumentType[])} argumentsDefs
     */
    _ensureArguments(argumentsObject, ...argumentsDefs) {
        if (!unconsumedMatchers.has(this)) {
            throw new HootError(
                `cannot use multiple matchers on the same \`expect()\` call`,
            );
        }
        unconsumedMatchers.delete(this);

        const args = [...argumentsObject];
        ensureArguments(args, ...argumentsDefs, ["object", null]);

        const options = args[argumentsDefs.length] || {};
        for (const flag in FLAGS) {
            if (flag in options) {
                if (options[flag]) {
                    this._flags |= FLAGS[flag];
                } else {
                    this._flags &= ~FLAGS[flag];
                }
            }
        }

        if (!(this._flags & FLAGS.headless)) {
            currentStack = getStack(1);
        }
    }

    /**
     * @private
     * @param {() => MatcherSpecifications<R, A>} specCallback
     * @returns {Async extends true ? Promise<boolean> : boolean}
     */
    _resolve(specCallback) {
        const isAsync = this._flags & (FLAGS.rejects | FLAGS.resolves);
        if (this._flags & FLAGS.error) {
            return isAsync ? new Promise(() => {}) : undefined;
        }
        if (isAsync) {
            return Promise.resolve(this._received).then(
                /** @param {PromiseFulfilledResult<R>} reason */
                (result) => {
                    if (this._flags & FLAGS.rejects) {
                        this._result.registerEvent("assertion", {
                            label: "rejects",
                            pass: false,
                            reportMessage: [
                                r`expected promise to reject, instead resolved with:`,
                                result,
                            ],
                        });
                        return false;
                    } else {
                        this._received = result;
                        return this._resolveFinalResult(specCallback);
                    }
                },
                /** @param {PromiseRejectedResult} reason */
                (reason) => {
                    if (this._flags & FLAGS.resolves) {
                        this._result.registerEvent("assertion", {
                            label: "resolves",
                            pass: false,
                            reportMessage: [
                                r`expected promise to resolve, instead rejected with:`,
                                reason,
                            ],
                        });
                        return false;
                    } else {
                        this._received = reason;
                        return this._resolveFinalResult(specCallback);
                    }
                },
            );
        } else {
            return this._resolveFinalResult(specCallback);
        }
    }

    /**
     * @private
     * @param {() => MatcherSpecifications<R, A>} specCallback
     * @returns {boolean}
     */
    _resolveFinalResult(specCallback) {
        let {
            acceptedType,
            getFailedDetails,
            mapElements,
            message,
            name,
            onFail,
            onPass,
            predicate,
        } = specCallback();

        const types = ensureArray(acceptedType);
        if (!types.some((type) => isOfType(this._received, type))) {
            const joinedTypes =
                types.length > 1
                    ? new ListFormat("en-GB", {
                          type: "disjunction",
                          style: "long",
                      }).format(types)
                    : types[0];
            throw new TypeError(
                `expected received value to be of type ${joinedTypes}, got ${formatHumanReadable(
                    this._received,
                )}`,
            );
        }

        if (mapElements) {
            this._received = new ElementMap(this._received, mapElements);
        }
        function passPredicate(...args) {
            return not ? !predicate(...args) : predicate(...args);
        }
        const not = this._flags & FLAGS.not;
        let pass;
        if (mapElements) {
            pass = this._received.every(passPredicate);
            if (!pass && !this._received.size) {
                onFail = [r`expected at least`, 1, r`element and got`, this._received];
            }
        } else {
            pass = passPredicate(this._received);
        }

        if (!(this._flags & FLAGS.silent)) {
            const assertion = {
                flags: this._flags,
                label: name,
                message,
                pass,
                reportMessage: pass ? onPass : onFail,
            };
            if (!pass) {
                if (mapElements) {
                    assertion.failedDetails = this._received.mapFailedDetails(
                        getFailedDetails,
                        passPredicate,
                    );
                } else {
                    assertion.failedDetails = getFailedDetails(this._received);
                }
                assertion.stack = currentStack;
            }
            this._result.registerEvent("assertion", assertion);
        }

        return pass;
    }

    /**
     * @private
     * @param {"toHaveInnerHTML" | "toHaveOuterHTML"} name
     * @param {"innerHTML" | "outerHTML"} property
     * @param {string | RegExp} expected
     * @param {ExpectOptions & FormatXmlOptions} [options]
     */
    _toHaveHTML(name, property, expected, options) {
        options = { type: "html", ...options };
        if (!isInstanceOf(expected, RegExp)) {
            expected = formatXml(expected, options);
        }

        return this._resolve(() => ({
            name,
            acceptedType: ["string", "node", "node[]"],
            mapElements: (el) => formatXml(el[property], { ...options, type: "html" }),
            predicate: (elHtml) => valueMatches(elHtml, expected),
            message: options?.message,
            onPass: () => [
                property,
                r`of`,
                this._received,
                r`is[! not] equal to expected value`,
            ],
            onFail: () => [
                r`expected`,
                property,
                r`of`,
                this._received,
                r`to match the given value`,
            ],
            getFailedDetails: (val) => detailsFromValuesWithDiff(expected, val),
        }));
    }
}

export class CaseEvent {
    label = "";
    /** @type {(string | Label)[]} */
    message = [];
    ts = $floor($now());
    /** @type {number} */
    type;
}

export class Assertion extends CaseEvent {
    /** @type {string | null | undefined} */
    additionalMessage;
    /** @type {string | undefined} */
    docLabel;
    type = CASE_EVENT_TYPES.assertion.value;

    /**
     * @param {number} number
     * @param {Partial<Assertion & {
     *  docLabel?: string;
     *  message: AssertionMessage,
     *  reportMessage: AssertionReportMessage,
     * }>} values
     */
    constructor(number, values) {
        super();

        this.docLabel = values.docLabel;
        this.label = values.label;
        this.flags = values.flags || 0;
        this.pass = values.pass || false;
        this.number = number;

        if (!this.pass) {
            /** @type {[any, any][] | null} */
            this.failedDetails = Markup.resolveDetails(values.failedDetails || []);
            /** @type {string} */
            this.stack = values.stack;
        }

        let { message, reportMessage } = values;

        if (typeof message === "function") {
            this.additionalMessage = message();
        } else {
            this.additionalMessage = message;
        }

        if (typeof reportMessage === "function") {
            reportMessage = reportMessage(this.pass, r);
        }
        const parts =
            $isArray(reportMessage) && !isLabel(reportMessage)
                ? reportMessage
                : [makeLabel(reportMessage, null)];
        const plural = parts.some((p) => p instanceof ElementMap && p.size !== 1);
        const not = this.flags & FLAGS.not;
        for (const part of parts) {
            if (part instanceof ElementMap) {
                const subject = part.size === 1 ? "element" : "elements";
                if (part.selector) {
                    this.message.push(
                        makeLabelOrString(part.size),
                        `${subject} matching`,
                        makeLabelOrString(part.selector),
                    );
                } else {
                    const elements = part.keys();
                    this.message.push(
                        subject,
                        makeLabelOrString(
                            part.size === 1 ? elements.next().value : [...elements],
                        ),
                    );
                }
            } else if (isLabel(part)) {
                if (part[1] === "icon") {
                    this.message.push(part);
                } else {
                    this.message.push(
                        makeLabelOrString(formatMessage(part[0], plural, not), part[1]),
                    );
                }
            } else if (typeof part === "string") {
                this.message.push(makeLabelOrString(formatMessage(part, plural, not)));
            } else {
                this.message.push(makeLabelOrString(part));
            }
        }
    }

    /**
     * @param {keyof typeof FLAGS} name
     */
    hasFlag(name) {
        return this.flags & FLAGS[name];
    }
}

export class DOMCaseEvent extends CaseEvent {
    /**
     * @param {InteractionType} type
     * @param {InteractionDetails} details
     */
    constructor(type, [name, alias, args, returnValue]) {
        super();

        this.type = CASE_EVENT_TYPES[type].value;
        this.label = alias || name;
        if (type === "server") {
            this.docLabel = mockFetch.name;
        } else {
            this.docLabel = name;
        }
        for (let i = 0; i < args.length; i++) {
            if (args[i] !== undefined && (i === 0 || typeof args[i] !== "object")) {
                this.message.push(makeLabelOrString(args[i]));
            }
        }
        if (returnValue && type === "query" && returnValue !== args[0]) {
            this.message.push(ARROW_RIGHT, makeLabelOrString(returnValue));
        }
    }
}

export class CaseError extends CaseEvent {
    type = CASE_EVENT_TYPES.error.value;

    /**
     * @param {Error} error
     */
    constructor(error) {
        super();

        /** @type {Error | null} */
        this.cause = error.cause || null;
        this.label = error.name;
        this.message = error.message.split(R_WHITE_SPACE);
        /** @type {string} */
        this.stack = error.stack;

        const errorNameAndMessage = String(error);
        if (!this.stack.startsWith(errorNameAndMessage)) {
            this.stack = errorNameAndMessage + this.stack.slice(error.name.length);
        }
    }
}

export class Step extends CaseEvent {
    type = CASE_EVENT_TYPES.step.value;
    label = "step";
    docLabel = "expect.step";

    /**
     * @param {any} value
     */
    constructor(value) {
        super();

        this.message = [makeLabel(value)];
    }
}
