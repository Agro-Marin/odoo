// @ts-check
/** @odoo-module native */

import { foldForCaseInsensitiveCompare } from "@web/core/l10n/utils/unaccent";
import { shallowEqual } from "@web/core/utils/collections/objects";
import { LruCache } from "@web/core/utils/lru_cache";
import { session } from "@web/session";

import { ASTType } from "./py_js/ast_type.js";
import { evaluate, formatAST, parseExpr } from "./py_js/py.js";
import { EvaluationError } from "./py_js/py_builtin.js";
import { isEqual, isIn } from "./py_js/py_compare.js";
import { toPyValue } from "./py_js/py_utils.js";

/**
 * @typedef {import("./py_js/ast_type.js").AST} AST
 */
/** @typedef {import("./py_js/ast_type.js").ASTList} ASTList */

/**
 * @typedef {[string | 0 | 1, string, any]} Condition
 * @typedef {("&" | "|" | "!" | Condition)[]} DomainListRepr
 * @typedef {DomainListRepr | string | Domain} DomainRepr
 */

export class InvalidDomainError extends Error {}

export class Domain {
    /**
     * @type {ASTList}
     */
    ast;

    /**
     * @param {DomainRepr[]} domains
     * @param {"AND" | "OR"} operator
     * @returns {Domain}
     */
    static combine(domains, operator) {
        const nonEmpty = domains
            .map((d) => (d instanceof Domain ? d : new Domain(d)))
            .filter((d) => d.ast.value.length);
        if (!nonEmpty.length) {
            return new Domain([]);
        }
        if (nonEmpty.length === 1) {
            return Domain.fromASTValue([...nonEmpty[0].ast.value]);
        }
        const op = operator === "AND" ? "&" : "|";
        const value = [];
        for (let i = 0; i < nonEmpty.length - 1; i++) {
            value.push({ type: ASTType.String, value: op });
            value.push(...nonEmpty[i].ast.value);
        }
        value.push(.../** @type {Domain} */ (nonEmpty.at(-1)).ast.value);
        return Domain.fromASTValue(value);
    }

    /**
     * @param {DomainRepr[]} domains
     * @returns {Domain}
     */
    static and(domains) {
        return Domain.combine(domains, "AND");
    }

    /**
     * @param {DomainRepr[]} domains
     * @returns {Domain}
     */
    static or(domains) {
        return Domain.combine(domains, "OR");
    }

    /**
     * @param {DomainRepr} domain
     * @returns {Domain}
     */
    static not(domain) {
        const result = new Domain(domain);
        if (!result.ast.value.length) {
            return new Domain([FALSE_LEAF]);
        }
        return Domain.fromASTValue([
            { type: ASTType.String, value: "!" },
            ...result.ast.value,
        ]);
    }

    /**
     * @param {DomainRepr} domain
     * @param {string[]} keysToRemove
     * @return {Domain}
     */
    static removeDomainLeaves(domain, keysToRemove) {
        /**
         * @param {AST[]} elements
         * @returns {{ sizes: number[], fullyRemoved: boolean[] }}
         */
        function computeSubtreeSizes(elements) {
            const sizes = new Array(elements.length).fill(0);
            const fullyRemoved = new Array(elements.length).fill(false);
            for (let idx = elements.length - 1; idx >= 0; idx--) {
                const node = elements[idx];
                if (isDomainLeaf(node)) {
                    sizes[idx] = 1;
                    fullyRemoved[idx] = keysToRemove.includes(
                        /** @type {any} */ (node).value[0].value,
                    );
                } else if (node.type === ASTType.String) {
                    if (node.value === "!") {
                        sizes[idx] = 1 + sizes[idx + 1];
                        fullyRemoved[idx] = fullyRemoved[idx + 1];
                    } else if (node.value === "&" || node.value === "|") {
                        const firstSize = sizes[idx + 1];
                        sizes[idx] = 1 + firstSize + sizes[idx + 1 + firstSize];
                        fullyRemoved[idx] =
                            fullyRemoved[idx + 1] && fullyRemoved[idx + 1 + firstSize];
                    }
                }
            }
            return { sizes, fullyRemoved };
        }

        /** @type {number[]} */
        let sizes;
        /** @type {boolean[]} */
        let fullyRemoved;

        /**
         * @param {string} operatorCtx
         * @param {AST[]} output
         */
        function pushNeutral(operatorCtx, output) {
            if (operatorCtx === "&") {
                output.push(...Domain.TRUE.ast.value);
            } else if (operatorCtx === "|") {
                output.push(...Domain.FALSE.ast.value);
            }
        }

        /**
         * @param {AST[]} elements
         * @param {number} idx
         * @param {string} operatorCtx
         * @param {AST[]} output
         * @returns {number}
         */
        function processLeaf(elements, idx, operatorCtx, output) {
            const leaf = elements[idx];
            if (isDomainLeaf(leaf)) {
                if (keysToRemove.includes(/** @type {any} */ (leaf).value[0].value)) {
                    pushNeutral(operatorCtx, output);
                } else {
                    output.push(leaf);
                }
                return 1;
            } else if (leaf.type === ASTType.String) {
                if (leaf.value !== operatorCtx && fullyRemoved[idx]) {
                    pushNeutral(operatorCtx, output);
                    return sizes[idx];
                }
                if (leaf.value === "!") {
                    const invertedCtx = operatorCtx === "&" ? "|" : "&";
                    output.push(leaf);
                    return 1 + processLeaf(elements, idx + 1, invertedCtx, output);
                }
                output.push(leaf);
                const firstLeafSkip = processLeaf(
                    elements,
                    idx + 1,
                    leaf.value,
                    output,
                );
                const secondLeafSkip = processLeaf(
                    elements,
                    idx + 1 + firstLeafSkip,
                    leaf.value,
                    output,
                );
                return 1 + firstLeafSkip + secondLeafSkip;
            }
            return 0;
        }

        domain = new Domain(domain);
        if (!domain.ast.value.length) {
            return domain;
        }
        ({ sizes, fullyRemoved } = computeSubtreeSizes(domain.ast.value));
        /** @type {AST[]} */
        const value = [];
        processLeaf(domain.ast.value, 0, "&", value);
        return Domain.fromASTValue(value);
    }

    /**
     * @param {AST[]} value
     * @returns {Domain}
     */
    static fromASTValue(value) {
        const domain = new Domain([]);
        domain.ast = { type: ASTType.List, value };
        return domain;
    }

    /**
     * @param {DomainRepr} [descr]
     */
    constructor(descr = []) {
        if (descr instanceof Domain) {
            this.ast = { type: descr.ast.type, value: [...descr.ast.value] };
        } else {
            let rawAST;
            try {
                rawAST = typeof descr === "string" ? parseExpr(descr) : toAST(descr);
            } catch (error) {
                throw new InvalidDomainError(
                    `Invalid domain representation: ${descr.toString()}`,
                    {
                        cause: error,
                    },
                );
            }
            this.ast = /** @type {ASTList} */ (normalizeDomainAST(rawAST));
        }
    }

    /**
     * @param {Record<string, any>} record
     * @returns {boolean}
     */
    contains(record) {
        return this.compile()(record);
    }

    /**
     * @returns {RecordPredicate}
     */
    compile() {
        const ast = this.ast;
        let predicate = compiledDomains.get(ast);
        if (predicate) {
            return predicate;
        }
        const key = `${serverFoldsAccents() ? "u" : "-"}\x00${formatAST(ast)}`;
        predicate = compiledDomainsByKey.get(key);
        if (!predicate) {
            predicate = isLiteralAST(ast)
                ? compileDomainList(evaluate(ast, {}))
                : (record) => matchDomain(record, evaluate(ast, record));
            compiledDomainsByKey.set(key, predicate);
        }
        compiledDomains.set(ast, predicate);
        return predicate;
    }

    /**
     * @template {Record<string, any>} T
     * @param {T[]} records
     * @returns {T[]}
     */
    filter(records) {
        return records.filter(this.compile());
    }

    /**
     * @returns {string}
     */
    toString() {
        return formatAST(this.ast);
    }

    /**
     * @param {Object} [context]
     * @returns {DomainListRepr}
     */
    toList(context) {
        try {
            return evaluate(this.ast, context);
        } catch (error) {
            if (error instanceof EvaluationError) {
                throw new InvalidDomainError(error.message, { cause: error });
            }
            throw error;
        }
    }

    /**
     * @returns {DomainListRepr | string}
     */
    toJson() {
        try {
            const evaluatedAsList = this.toList({});
            const evaluatedDomain = new Domain(evaluatedAsList);
            if (evaluatedDomain.toString() === this.toString()) {
                return evaluatedAsList;
            }
            return this.toString();
        } catch {
            return this.toString();
        }
    }
}

/** @type {Condition} */
const TRUE_LEAF = [1, "=", 1];
/** @type {Condition} */
const FALSE_LEAF = [0, "=", 1];
/**
 * @template {Domain} T
 * @param {T} domain
 * @returns {T}
 */
function freezeDomain(domain) {
    for (const node of domain.ast.value) {
        Object.freeze(node);
        Object.freeze(/** @type {any} */ (node).value);
    }
    Object.freeze(domain.ast.value);
    Object.freeze(domain.ast);
    return Object.freeze(domain);
}

const TRUE_DOMAIN = freezeDomain(new Domain([TRUE_LEAF]));
const FALSE_DOMAIN = freezeDomain(new Domain([FALSE_LEAF]));

Domain.TRUE = TRUE_DOMAIN;
Domain.FALSE = FALSE_DOMAIN;

/**
 * @param {AST} node
 * @returns {boolean}
 */
function isDomainLeaf(node) {
    return node.type === ASTType.Tuple || node.type === ASTType.List;
}

/**
 * @param {DomainListRepr} domain
 * @returns {AST}
 */
function toAST(domain) {
    const elems = domain.map((elem) => {
        switch (elem) {
            case "!":
            case "&":
            case "|":
                return { type: ASTType.String, value: elem };
            default:
                return {
                    type: ASTType.Tuple,
                    value: elem.map(toPyValue),
                };
        }
    });
    return { type: ASTType.List, value: elems };
}

/**
 * @param {AST} domain
 * @param {'&' | '|'} [op]
 * @returns {AST}
 */

function normalizeDomainAST(domain, op = "&") {
    if (domain.type !== ASTType.List) {
        if (domain.type === ASTType.Tuple) {
            const value = domain.value;
            if (
                !value.some((e) => e.type === ASTType.Tuple) ||
                !value.every(
                    (e) => e.type === ASTType.Tuple || e.type === ASTType.String,
                )
            ) {
                throw new InvalidDomainError("Invalid domain AST");
            }
        } else {
            throw new InvalidDomainError("Invalid domain AST");
        }
    }
    if (!domain.value.length) {
        return { type: domain.type, value: [] };
    }
    /** @type {AST[]} */
    const body = [];
    let expected = 1;
    let joins = 0;
    for (const child of domain.value) {
        if (expected === 0) {
            joins++;
            expected = 1;
        }
        switch (child.type) {
            case ASTType.String:
                if (child.value === "&" || child.value === "|") {
                    expected++;
                } else if (child.value !== "!") {
                    throw new InvalidDomainError("Invalid domain AST");
                }
                break;
            case ASTType.List:
            case ASTType.Tuple:
                if (child.value.length !== 3) {
                    throw new InvalidDomainError("Invalid domain AST");
                }
                expected--;
                break;
            default:
                throw new InvalidDomainError("Invalid domain AST");
        }
        body.push(child);
    }
    if (expected > 0) {
        throw new InvalidDomainError(
            `invalid domain ${formatAST(domain)} (missing ${expected} segment(s))`,
        );
    }
    /** @type {AST[]} */
    const values = new Array(joins + body.length);
    for (let i = 0; i < joins; i++) {
        values[i] = { type: ASTType.String, value: op };
    }
    for (let i = 0; i < body.length; i++) {
        values[joins + i] = body[i];
    }
    return { type: ASTType.List, value: values };
}

/**
 * @typedef {{ lit?: string, any?: boolean, one?: boolean }[]} LikePattern
 */

/**
 * @param {any} value
 * @param {boolean} anchored
 * @returns {LikePattern}
 */
function parseLikePattern(value, anchored) {
    const pattern = String(value);
    /** @type {LikePattern} */
    const tokens = [];
    let literal = "";
    const flushLiteral = () => {
        if (literal) {
            tokens.push({ lit: literal });
            literal = "";
        }
    };
    if (!anchored) {
        tokens.push({ any: true });
    }
    let escaped = false;
    for (const ch of pattern) {
        if (escaped) {
            escaped = false;
            literal += ch;
        } else if (ch === "\\") {
            escaped = true;
        } else if (ch === "%") {
            flushLiteral();
            if (!tokens.at(-1)?.any) {
                tokens.push({ any: true });
            }
        } else if (ch === "_") {
            flushLiteral();
            tokens.push({ one: true });
        } else {
            literal += ch;
        }
    }
    flushLiteral();
    if (!anchored && !tokens.at(-1)?.any) {
        tokens.push({ any: true });
    }
    return tokens;
}

/**
 * @param {string} str
 * @param {number} index
 * @returns {number}
 */
function nextCharIndex(str, index) {
    const code = str.charCodeAt(index);
    const isHighSurrogate = code >= 0xd800 && code <= 0xdbff;
    return index + (isHighSurrogate && index + 1 < str.length ? 2 : 1);
}

/**
 * @param {LikePattern} tokens
 * @param {string} str
 * @returns {boolean}
 */
function likeMatch(tokens, str) {
    const nTokens = tokens.length;
    const nChars = str.length;
    let tokenIdx = 0;
    let charIdx = 0;
    let wildcardTokenIdx = -1;
    let wildcardCharIdx = 0;
    while (charIdx < nChars) {
        const token = tokenIdx < nTokens ? tokens[tokenIdx] : undefined;
        if (token?.one) {
            charIdx = nextCharIndex(str, charIdx);
            tokenIdx++;
            continue;
        }
        if (token?.any) {
            wildcardTokenIdx = tokenIdx++;
            wildcardCharIdx = charIdx;
            continue;
        }
        if (token?.lit !== undefined && str.startsWith(token.lit, charIdx)) {
            charIdx += token.lit.length;
            tokenIdx++;
            continue;
        }
        if (wildcardTokenIdx === -1) {
            return false;
        }
        tokenIdx = wildcardTokenIdx + 1;
        wildcardCharIdx = nextCharIndex(str, wildcardCharIdx);
        charIdx = wildcardCharIdx;
    }
    while (tokenIdx < nTokens && tokens[tokenIdx].any) {
        tokenIdx++;
    }
    return tokenIdx === nTokens;
}

/**
 * @param {any} value
 * @returns {boolean}
 */
function isUnsetValue(value) {
    return value === false || value === null;
}

/**
 * @param {any} value
 * @returns {boolean}
 */
function isAbsentValue(value) {
    return value === undefined;
}

/**
 * @returns {boolean}
 */
function serverFoldsAccents() {
    return session.has_unaccent ?? true;
}

/**
 * @param {any} value
 * @returns {boolean}
 */
function isDateLiteral(value) {
    return (
        typeof value === "string" &&
        /^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}:\d{2}(\.\d+)?)?$/.test(value)
    );
}

/**
 * @param {any} value
 * @returns {any}
 */
function asComparableText(value) {
    return isUnsetValue(value) ? "" : value;
}

/** @typedef {(record: Record<string, any>) => boolean} RecordPredicate */

/**
 * @param {Condition | boolean} condition
 * @returns {RecordPredicate}
 */
function compileCondition(condition) {
    if (typeof condition === "boolean") {
        return () => condition;
    }
    const [field, operator, value] = condition;

    if (typeof field === "string") {
        const names = field.split(".");
        if (names.length >= 2) {
            const head = names[0];
            const restField = names.slice(1).join(".");
            const matchRest = compileCondition([restField, operator, value]);
            const absentParent = { [restField]: false };
            return (record) => {
                const parent = record[head];
                return matchRest(
                    !parent || typeof parent !== "object" ? absentParent : parent,
                );
            };
        }
    }
    if (typeof operator !== "string") {
        return () => {
            throw new InvalidDomainError(
                `invalid domain (operator must be a string, got ${typeof operator})`,
            );
        };
    }
    const op = operator.toLowerCase();
    const isNot = op.startsWith("not ");
    /** @type {(record: Record<string, any>) => any} */
    const readField =
        typeof field === "number" ? () => field : (record) => record[field];

    switch (op) {
        case "=?":
            return value ? compileCondition([field, "=", value]) : () => true;
        case "=":
        case "==": {
            if (isUnsetValue(value) || value === "") {
                return (record) => {
                    const fieldValue = readField(record);
                    return Array.isArray(fieldValue)
                        ? fieldValue.length === 0
                        : fieldValue !== undefined && !fieldValue;
                };
            }
            if (Array.isArray(value)) {
                return (record) => {
                    const fieldValue = readField(record);
                    return Array.isArray(fieldValue)
                        ? shallowEqual(fieldValue, value)
                        : isEqual(fieldValue, value);
                };
            }
            return (record) => isEqual(readField(record), value);
        }
        case "!=":
        case "<>": {
            const matchEqual = compileCondition([field, "=", value]);
            return (record) => !matchEqual(record);
        }
        case "<":
        case "<=":
        case ">":
        case ">=": {
            const rightIsDateLiteral = isDateLiteral(value);
            const compare =
                op === "<"
                    ? (/** @type {any} */ a, /** @type {any} */ b) => a < b
                    : op === "<="
                      ? (/** @type {any} */ a, /** @type {any} */ b) => a <= b
                      : op === ">"
                        ? (/** @type {any} */ a, /** @type {any} */ b) => a > b
                        : (/** @type {any} */ a, /** @type {any} */ b) => a >= b;
            return (record) => {
                const fieldValue = readField(record);
                if (isAbsentValue(fieldValue)) {
                    return false;
                }
                let left = fieldValue;
                let right = value;
                if (isUnsetValue(left) || isUnsetValue(right)) {
                    if (rightIsDateLiteral || isDateLiteral(left)) {
                        return false;
                    }
                    const zero =
                        typeof left === "number" || typeof right === "number" ? 0 : "";
                    left = isUnsetValue(left) ? zero : left;
                    right = isUnsetValue(right) ? zero : right;
                }
                return compare(left, right);
            };
        }
        case "in":
        case "not in": {
            const values = Array.isArray(value) ? value : [value];
            const selectsUnset = values.some(
                (v) => v === false || v === null || v === "",
            );
            return (record) => {
                const fieldValue = readField(record);
                const fieldValues = Array.isArray(fieldValue)
                    ? fieldValue
                    : [fieldValue];
                let matched = fieldValues.some((fv) => isIn(fv, values));
                if (!matched && selectsUnset) {
                    matched = Array.isArray(fieldValue)
                        ? fieldValue.length === 0
                        : fieldValue !== undefined && !fieldValue;
                }
                return matched !== isNot;
            };
        }
        case "like":
        case "not like":
        case "=like":
        case "not =like":
        case "ilike":
        case "not ilike":
        case "=ilike":
        case "not =ilike": {
            const anchored = op.startsWith("=") || op.startsWith("not =");
            const fold = op.endsWith("ilike")
                ? (/** @type {string} */ s) =>
                      foldForCaseInsensitiveCompare(s, serverFoldsAccents())
                : (/** @type {string} */ s) => s;
            const tokens = parseLikePattern(
                fold(String(asComparableText(value))),
                anchored,
            );
            return (record) => {
                const fieldValue = readField(record);
                if (isAbsentValue(fieldValue)) {
                    return isNot;
                }
                const subject = fold(String(asComparableText(fieldValue)));
                return likeMatch(tokens, subject) !== isNot;
            };
        }
        case "any":
        case "any!":
        case "child_of":
        case "parent_of":
            return () => true;
        case "not any":
        case "not any!":
            return () => false;
    }
    return () => {
        throw new InvalidDomainError("could not match domain");
    };
}

/**
 * @param {DomainListRepr} domain
 * @returns {RecordPredicate}
 */
function compileDomainList(domain) {
    if (!domain.length) {
        return () => true;
    }
    let cursor = 0;
    /** @returns {RecordPredicate} */
    const parseOperand = () => {
        if (cursor >= domain.length) {
            throw new InvalidDomainError("invalid domain (missing operand(s))");
        }
        const item = domain[cursor++];
        switch (item) {
            case "!": {
                const operand = parseOperand();
                return (record) => !operand(record);
            }
            case "&": {
                const left = parseOperand();
                const right = parseOperand();
                return (record) => left(record) && right(record);
            }
            case "|": {
                const left = parseOperand();
                const right = parseOperand();
                return (record) => left(record) || right(record);
            }
        }
        return compileCondition(/** @type {Condition} */ (item));
    };
    const predicate = parseOperand();
    if (cursor !== domain.length) {
        throw new InvalidDomainError("invalid domain (unconsumed segment(s))");
    }
    return predicate;
}

/**
 * @param {Record<string, any>} record
 * @param {DomainListRepr} domain
 * @returns {boolean}
 */
function matchDomain(record, domain) {
    return compileDomainList(domain)(record);
}

/**
 * @type {Set<AST["type"]>}
 */
const LITERAL_AST_TYPES = new Set([
    ASTType.List,
    ASTType.Tuple,
    ASTType.String,
    ASTType.Number,
    ASTType.Boolean,
    ASTType.None,
]);

/**
 * @param {AST} ast
 * @returns {boolean}
 */
function isLiteralAST(ast) {
    if (!LITERAL_AST_TYPES.has(ast.type)) {
        return false;
    }
    const { value } = /** @type {any} */ (ast);
    return Array.isArray(value) ? value.every(isLiteralAST) : true;
}

/**
 * @type {WeakMap<ASTList, RecordPredicate>}
 */
const compiledDomains = new WeakMap();

/**
 * @type {LruCache}
 */
const compiledDomainsByKey = new LruCache(512);
