// @ts-check
/** @odoo-module native */

/** @module @web/core/domain - Domain expression AST: parsing, combining, evaluation, and conversion to string */

import { shallowEqual } from "@web/core/utils/collections/objects";
import { escapeRegExp } from "@web/core/utils/format/strings";

import { evaluate, formatAST, parseExpr } from "./py_js/py.js";
import { EvaluationError } from "./py_js/py_builtin.js";
import { toPyValue } from "./py_js/py_utils.js";
import { ASTType } from "./py_js/ast_type.js";

/**
 * AST node — a discriminated union keyed on the literal ``type`` tag (see
 * {@link ASTType}); ``.type``/``switch`` checks narrow it to each node shape.
 * @typedef {import("./py_js/ast_type.js").AST} AST
 */
/** @typedef {import("./py_js/ast_type.js").ASTList} ASTList */

/**
 * @typedef {[string | 0 | 1, string, any]} Condition
 * @typedef {("&" | "|" | "!" | Condition)[]} DomainListRepr
 * @typedef {DomainListRepr | string | Domain} DomainRepr
 */

export class InvalidDomainError extends Error {}

/**
 * Javascript representation of an Odoo domain
 */
export class Domain {
    /**
     * The normalized domain AST — always a List node (see normalizeDomainAST).
     * @type {ASTList}
     */
    ast;

    /**
     * Combine various domains together with a given operator
     * @param {DomainRepr[]} domains
     * @param {"AND" | "OR"} operator
     * @returns {Domain}
     */
    static combine(domains, operator) {
        // Normalize all inputs to Domain instances and filter out empty ones
        const nonEmpty = domains
            .map((d) => (d instanceof Domain ? d : new Domain(d)))
            .filter((d) => d.ast.value.length);
        if (!nonEmpty.length) {
            return new Domain([]);
        }
        if (nonEmpty.length === 1) {
            return nonEmpty[0];
        }
        // Build the right-associated prefix form in a single pass — an operator
        // before each operand except the last (e.g. OR(d1,d2,d3) yields
        // ["|", ...d1, "|", ...d2, ...d3]). The previous recursive `slice(1)`
        // was O(N²) in AST size and recursed to depth N (stack-overflow risk for
        // large AND/OR merges); this is O(N) and iterative.
        const op = operator === "AND" ? "&" : "|";
        const value = [];
        for (let i = 0; i < nonEmpty.length - 1; i++) {
            value.push({ type: ASTType.String, value: op });
            value.push(...nonEmpty[i].ast.value);
        }
        value.push(...nonEmpty.at(-1).ast.value);
        const result = new Domain([]);
        result.ast = { type: ASTType.List, value };
        return result;
    }

    /**
     * Combine various domains together with `AND` operator
     * @param {DomainRepr[]} domains
     * @returns {Domain}
     */
    static and(domains) {
        return Domain.combine(domains, "AND");
    }

    /**
     * Combine various domains together with `OR` operator
     * @param {DomainRepr[]} domains
     * @returns {Domain}
     */
    static or(domains) {
        return Domain.combine(domains, "OR");
    }

    /**
     * Return the negation of the domain
     * @param {DomainRepr} domain
     * @returns {Domain}
     */
    static not(domain) {
        const result = new Domain(domain);
        result.ast.value.unshift({ type: ASTType.String, value: "!" });
        return result;
    }

    /**
     * Return a new domain with `neutralized` leaves (for the leaves that are applied on the field that are part of
     * keysToRemove).
     * @param {DomainRepr} domain
     * @param {string[]} keysToRemove
     * @return {Domain}
     */
    static removeDomainLeaves(domain, keysToRemove) {
        /**
         * Return how many AST elements the subtree rooted at ``idx`` spans.
         * @param {AST[]} elements
         * @param {number} idx
         * @returns {number}
         */
        function subtreeSize(elements, idx) {
            const node = elements[idx];
            if (node.type === ASTType.Tuple) {
                return 1;
            }
            if (node.type === ASTType.String) {
                if (node.value === "!") {
                    return 1 + subtreeSize(elements, idx + 1);
                }
                if (node.value === "&" || node.value === "|") {
                    const firstSize = subtreeSize(elements, idx + 1);
                    return 1 + firstSize + subtreeSize(elements, idx + 1 + firstSize);
                }
            }
            return 0;
        }

        /**
         * True if every leaf in the subtree at ``idx`` is in keysToRemove.
         * @param {AST[]} elements
         * @param {number} idx
         * @returns {boolean}
         */
        function isFullyRemoved(elements, idx) {
            const node = elements[idx];
            if (node.type === ASTType.Tuple) {
                return keysToRemove.includes(/** @type {any} */ (node.value[0]).value);
            }
            if (node.type === ASTType.String) {
                if (node.value === "!") {
                    return isFullyRemoved(elements, idx + 1);
                }
                if (node.value === "&" || node.value === "|") {
                    const firstSize = subtreeSize(elements, idx + 1);
                    return (
                        isFullyRemoved(elements, idx + 1) &&
                        isFullyRemoved(elements, idx + 1 + firstSize)
                    );
                }
            }
            return false;
        }

        /**
         * Push the neutral identity value for the given operator context.
         * @param {string} operatorCtx
         * @param {Domain} newDomain
         */
        function pushNeutral(operatorCtx, newDomain) {
            if (operatorCtx === "&") {
                newDomain.ast.value.push(...Domain.TRUE.ast.value);
            } else if (operatorCtx === "|") {
                newDomain.ast.value.push(...Domain.FALSE.ast.value);
            }
        }

        /**
         * @param {AST[]} elements
         * @param {number} idx
         * @param {string} operatorCtx
         * @param {Domain} newDomain
         * @returns {number}
         */
        function processLeaf(elements, idx, operatorCtx, newDomain) {
            const leaf = elements[idx];
            if (leaf.type === ASTType.Tuple) {
                if (keysToRemove.includes(/** @type {any} */ (leaf.value[0]).value)) {
                    pushNeutral(operatorCtx, newDomain);
                } else {
                    newDomain.ast.value.push(leaf);
                }
                return 1;
            } else if (leaf.type === ASTType.String) {
                // Special case: both children of OR are removed leaves —
                // replace the whole OR+children with a single neutral value.
                if (
                    leaf.value === "|" &&
                    elements[idx + 1].type === ASTType.Tuple &&
                    elements[idx + 2].type === ASTType.Tuple &&
                    keysToRemove.includes(/** @type {any} */ (elements[idx + 1]).value[0].value) &&
                    keysToRemove.includes(/** @type {any} */ (elements[idx + 2]).value[0].value)
                ) {
                    pushNeutral(operatorCtx, newDomain);
                    return 3;
                }
                if (leaf.value === "!") {
                    const childSize = subtreeSize(elements, idx + 1);
                    if (isFullyRemoved(elements, idx + 1)) {
                        // The entire negated subtree is removed. Replace
                        // "!" + subtree with a neutral value. Without this,
                        // we'd emit ["!", TRUE_LEAF] = NOT(TRUE) = FALSE,
                        // which silently filters out all records.
                        pushNeutral(operatorCtx, newDomain);
                        return 1 + childSize;
                    }
                    newDomain.ast.value.push(leaf);
                    return 1 + processLeaf(elements, idx + 1, "&", newDomain);
                }
                newDomain.ast.value.push(leaf);
                const firstLeafSkip = processLeaf(
                    elements,
                    idx + 1,
                    leaf.value,
                    newDomain,
                );
                const secondLeafSkip = processLeaf(
                    elements,
                    idx + 1 + firstLeafSkip,
                    leaf.value,
                    newDomain,
                );
                return 1 + firstLeafSkip + secondLeafSkip;
            }
            return 0;
        }

        domain = new Domain(domain);
        if (!domain.ast.value.length) {
            return domain;
        }
        const newDomain = new Domain([]);
        processLeaf(domain.ast.value, 0, "&", newDomain);
        return newDomain;
    }

    /**
     * @param {DomainRepr} [descr]
     */
    constructor(descr = []) {
        if (descr instanceof Domain) {
            return new Domain(descr.toString());
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
            // normalizeDomainAST always yields a List node (it throws otherwise).
            this.ast = /** @type {ASTList} */ (normalizeDomainAST(rawAST));
        }
    }

    /**
     * Check if the set of records represented by a domain contains a record
     * Warning: smart dates (see parseSmartDateInput) are not handled here.
     *
     * @param {Record<string, any>} record
     * @returns {boolean}
     */
    contains(record) {
        const expr = evaluate(this.ast, record);
        return matchDomain(record, expr);
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
     * Converts the domain into a human-readable format for JSON representation.
     * If the domain does not contain any contextual value, it is converted to a list.
     * Otherwise, it is returned as a string.
     *
     * The string format is less readable due to escaped double quotes.
     * Example: "[\"&\",[\"user_id\",\"=\",uid],[\"team_id\",\"!=\",false]]"
     * @returns {DomainListRepr | string}
     */
    toJson() {
        try {
            // Attempt to evaluate the domain without context
            const evaluatedAsList = this.toList({});
            const evaluatedDomain = new Domain(evaluatedAsList);
            if (evaluatedDomain.toString() === this.toString()) {
                return evaluatedAsList;
            }
            return this.toString();
        } catch {
            // The domain couldn't be evaluated due to contextual values
            return this.toString();
        }
    }
}

/** @type {Condition} */
const TRUE_LEAF = [1, "=", 1];
/** @type {Condition} */
const FALSE_LEAF = [0, "=", 1];
const TRUE_DOMAIN = new Domain([TRUE_LEAF]);
const FALSE_DOMAIN = new Domain([FALSE_LEAF]);

Domain.TRUE = TRUE_DOMAIN;
Domain.FALSE = FALSE_DOMAIN;

// -----------------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------------

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
 * Normalizes a domain
 *
 * @param {AST} domain
 * @param {'&' | '|'} [op]
 * @returns {AST}
 */

function normalizeDomainAST(domain, op = "&") {
    if (domain.type !== ASTType.List) {
        if (domain.type === ASTType.Tuple) {
            const value = domain.value;
            /* Tuple contains at least one Tuple and optionally string */
            if (
                !value.some((e) => e.type === ASTType.Tuple) ||
                !value.every((e) => e.type === ASTType.Tuple || e.type === ASTType.String)
            ) {
                throw new InvalidDomainError("Invalid domain AST");
            }
        } else {
            throw new InvalidDomainError("Invalid domain AST");
        }
    }
    if (!domain.value.length) {
        // Return a fresh node, never the input. A string-built domain's AST
        // comes from the memoized ``parseExpr`` cache, so returning it as-is
        // makes every ``new Domain("[]")`` share one ``.ast.value`` array.
        // The in-place AST mutators (``Domain.not``'s ``unshift``,
        // ``removeDomainLeaves``'s ``push``) would then mutate that shared
        // cache entry, corrupting every empty domain built afterwards
        // process-wide (``Domain.not(new Domain([]))`` poisons the cache so
        // the next ``new Domain("[]")`` throws "invalid domain"). The
        // non-empty path below already ``slice()``s for the same reason.
        return { type: domain.type, value: [] };
    }
    let expected = 1;
    for (const child of domain.value) {
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
                if (child.value.length === 3) {
                    expected--;
                    break;
                }
                throw new InvalidDomainError("Invalid domain AST");
            default:
                throw new InvalidDomainError("Invalid domain AST");
        }
    }
    const values = domain.value.slice();
    while (expected < 0) {
        expected++;
        values.unshift({ type: ASTType.String, value: op });
    }
    if (expected > 0) {
        throw new InvalidDomainError(
            `invalid domain ${formatAST(domain)} (missing ${expected} segment(s))`,
        );
    }
    return { type: ASTType.List, value: values };
}

/**
 * @param {Record<string, any>} record
 * @param {Condition | boolean} condition
 * @returns {boolean}
 */
function matchCondition(record, condition) {
    if (typeof condition === "boolean") {
        return condition;
    }
    const [field, operator, value] = condition;

    if (typeof field === "string") {
        const names = field.split(".");
        if (names.length >= 2) {
            const parent = record[names[0]];
            const restField = names.slice(1).join(".");
            if (!parent || typeof parent !== "object") {
                // Falsy or primitive — can't traverse deeper. Resolve to false,
                // matching Odoo server behavior for empty relational fields.
                return matchCondition({ [restField]: false }, [restField, operator, value]);
            }
            return matchCondition(parent, [restField, operator, value]);
        }
    }
    const fieldValue = typeof field === "number" ? field : record[field];
    const isNot = operator.startsWith("not ");
    switch (operator) {
        case "=?":
            // When value is false or null the condition is always true;
            // otherwise =? behaves identically to =.
            if ([false, null].includes(value)) {
                return true;
            }
            return matchCondition(record, [field, "=", value]);
        case "=":
        case "==":
            if (Array.isArray(fieldValue) && Array.isArray(value)) {
                return shallowEqual(fieldValue, value);
            }
            return fieldValue === value;
        case "!=":
        case "<>":
            return !matchCondition(record, [field, "=", value]);
        case "<":
            return fieldValue < value;
        case "<=":
            return fieldValue <= value;
        case ">":
            return fieldValue > value;
        case ">=":
            return fieldValue >= value;
        case "in":
        case "not in": {
            const val = Array.isArray(value) ? value : [value];
            const fieldVal = Array.isArray(fieldValue) ? fieldValue : [fieldValue];
            return Boolean(fieldVal.some((fv) => val.includes(fv))) !== isNot;
        }
        case "like":
        case "not like": {
            if (fieldValue === false) {
                return isNot;
            }
            const pattern = escapeRegExp(value).replaceAll("%", ".*");
            return new RegExp(pattern).test(fieldValue) !== isNot;
        }
        case "=like":
        case "not =like":
            if (fieldValue === false) {
                return isNot;
            }
            return (
                new RegExp(
                    "^" + escapeRegExp(value).replaceAll("%", ".*") + "$",
                ).test(fieldValue) !== isNot
            );
        case "ilike":
        case "not ilike": {
            if (fieldValue === false) {
                return isNot;
            }
            const pattern = escapeRegExp(value).replaceAll("%", ".*");
            return new RegExp(pattern, "i").test(fieldValue) !== isNot;
        }
        case "=ilike":
        case "not =ilike":
            if (fieldValue === false) {
                return isNot;
            }
            return (
                Boolean(
                    new RegExp(
                        "^" + escapeRegExp(value).replaceAll("%", ".*") + "$",
                        "i",
                    ).test(fieldValue),
                ) !== isNot
            );
        case "any":
        case "not any":
            return true;
        case "child_of":
        case "parent_of":
            return true;
    }
    throw new InvalidDomainError("could not match domain");
}

/**
 * Number of stack operands consumed by each prefix operator.
 * Keeping arity explicit decouples the stack machine from Function.length,
 * which changes with default parameters and rest params.
 */
const OPERATOR_ARITY = { "!": 1, "&": 2, "|": 2 };

/**
 * @param {Record<string, any>} record
 * @returns {Record<string, (...args: (Condition | boolean)[]) => boolean>}
 */
function makeOperators(record) {
    const match = matchCondition.bind(null, record);
    return {
        "!": (/** @type {Condition | boolean} */ x) => !match(x),
        "&": (/** @type {Condition | boolean} */ a, /** @type {Condition | boolean} */ b) =>
            match(a) && match(b),
        "|": (/** @type {Condition | boolean} */ a, /** @type {Condition | boolean} */ b) =>
            match(a) || match(b),
    };
}

/**
 *
 * @param {Record<string, any>} record
 * @param {DomainListRepr} domain
 * @returns {boolean}
 */
function matchDomain(record, domain) {
    if (!domain.length) {
        return true;
    }
    const operators = makeOperators(record);
    // Iterate backwards in-place instead of allocating a reversed copy.
    /** @type {any[]} */
    const condStack = [];
    for (let i = domain.length - 1; i >= 0; i--) {
        const item = domain[i];
        const operator = typeof item === "string" && operators[item];
        if (operator) {
            const operands = condStack.splice(-OPERATOR_ARITY[item]);
            condStack.push(operator(...operands));
        } else {
            condStack.push(item);
        }
    }
    return matchCondition(record, condStack.pop());
}
