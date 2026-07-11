// @ts-check
/** @odoo-module native */

/** @module @web/core/domain - Domain expression AST: parsing, combining, evaluation, and conversion to string */

import { shallowEqual } from "@web/core/utils/collections/objects";
import { escapeRegExp } from "@web/core/utils/format/strings";

import { ASTType } from "./py_js/ast_type.js";
import { evaluate, formatAST, parseExpr } from "./py_js/py.js";
import { EvaluationError } from "./py_js/py_builtin.js";
import { toPyValue } from "./py_js/py_utils.js";

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
        if (!result.ast.value.length) {
            // An empty domain is TRUE; the server maps ~TRUE -> FALSE. Prefixing
            // "!" onto an empty AST would produce the malformed ["!"] (no
            // operand), which crashes toString()/contains() and the server
            // rejects. Return FALSE instead.
            return new Domain([FALSE_LEAF]);
        }
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
         * Subtree spans, memoized in one right-to-left pass: each element's
         * span only depends on spans at higher indices, so sizes[idx] is
         * O(1) to compute once its successors are known. The previous
         * from-scratch recomputation at every connector was O(N²) overall
         * and recursed to depth O(N) on the prefix chain.
         * @param {AST[]} elements
         * @returns {number[]}
         */
        function computeSubtreeSizes(elements) {
            const sizes = new Array(elements.length).fill(0);
            for (let idx = elements.length - 1; idx >= 0; idx--) {
                const node = elements[idx];
                if (node.type === ASTType.Tuple) {
                    sizes[idx] = 1;
                } else if (node.type === ASTType.String) {
                    if (node.value === "!") {
                        sizes[idx] = 1 + sizes[idx + 1];
                    } else if (node.value === "&" || node.value === "|") {
                        const firstSize = sizes[idx + 1];
                        sizes[idx] = 1 + firstSize + sizes[idx + 1 + firstSize];
                    }
                }
            }
            return sizes;
        }

        /** @type {number[]} */
        let sizes;

        /**
         * Return how many AST elements the subtree rooted at ``idx`` spans.
         * @param {AST[]} elements
         * @param {number} idx
         * @returns {number}
         */
        function subtreeSize(elements, idx) {
            return sizes[idx];
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
                // Generalized neutralization: when EVERY leaf of the subtree
                // rooted at a connector is removed, the whole subtree must
                // collapse to the neutral element of the ENCLOSING context
                // (TRUE inside "&", FALSE inside "|"), not be rebuilt
                // leaf-by-leaf. Rebuilding ["&", removed, removed] inside an
                // OR as AND(TRUE, TRUE) = TRUE would absorb the whole OR
                // (match ALL records); ["!", removed] would become
                // NOT(TRUE) = FALSE (match nothing).
                //
                // When the connector matches the enclosing context ("&"
                // inside "&", "|" inside "|"), recursing is already sound —
                // each removed leaf becomes the shared neutral element and,
                // e.g., AND(TRUE, TRUE) is the neutral TRUE — and it
                // preserves the historical leaf-per-leaf output shape.
                if (leaf.value !== operatorCtx && isFullyRemoved(elements, idx)) {
                    pushNeutral(operatorCtx, newDomain);
                    return subtreeSize(elements, idx);
                }
                if (leaf.value === "!") {
                    // Under a negation the roles of the neutral elements
                    // swap: a removed subtree inside "!" must evaluate so
                    // that NOT(subtree) is neutral for the outer context.
                    const invertedCtx = operatorCtx === "&" ? "|" : "&";
                    newDomain.ast.value.push(leaf);
                    return 1 + processLeaf(elements, idx + 1, invertedCtx, newDomain);
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
        sizes = computeSubtreeSizes(domain.ast.value);
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
     * Warning: the relational operators ``any``/``child_of``/``parent_of``
     * cannot be resolved without the related records, so they are treated as an
     * always-match approximation (``not any`` is the dual of ``any`` so that
     * negation stays consistent).
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
    // Simulate the prefix-notation parse (mirroring the server's
    // normalize_domain): ``expected`` is the number of operands still owed at
    // the current position. Counting operators/leaves without tracking
    // position would accept garbage such as [leaf, "&", leaf] — a complete
    // expression followed by a dangling operator — which the server rejects
    // and which the matching stack machine cannot evaluate.
    /** @type {AST[]} */
    const values = [];
    let expected = 1;
    for (const child of domain.value) {
        if (expected === 0) {
            // The expression is already complete: join the extra segment
            // with the implicit operator, as in [leaf, leaf] ≡ ["&", leaf, leaf].
            values.unshift({ type: ASTType.String, value: op });
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
        values.push(child);
    }
    if (expected > 0) {
        throw new InvalidDomainError(
            `invalid domain ${formatAST(domain)} (missing ${expected} segment(s))`,
        );
    }
    return { type: ASTType.List, value: values };
}

/**
 * Translate a SQL LIKE pattern into a (non-anchored) regular-expression source
 * string, mirroring the PostgreSQL LIKE semantics used by the server:
 *  - ``%`` matches any run of characters -> ``.*``
 *  - ``_`` matches exactly one character -> ``.``
 *  - ``\`` escapes the next character, so ``\%``/``\_``/``\\`` match a literal
 *    ``%``/``_``/``\`` (and any other ``\x`` a literal ``x``).
 * Every other character is regex-escaped. The value is coerced with String()
 * so a numeric operand does not crash escapeRegExp.
 * @param {any} value
 * @returns {string}
 */
function likeToRegExp(value) {
    const pattern = String(value);
    let out = "";
    for (let i = 0; i < pattern.length; i++) {
        const ch = pattern[i];
        if (ch === "\\" && i + 1 < pattern.length) {
            // Escaped character: emit it literally (regex-escaped).
            out += escapeRegExp(pattern[++i]);
        } else if (ch === "%") {
            out += ".*";
        } else if (ch === "_") {
            out += ".";
        } else {
            out += escapeRegExp(ch);
        }
    }
    return out;
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
                return matchCondition({ [restField]: false }, [
                    restField,
                    operator,
                    value,
                ]);
            }
            return matchCondition(parent, [restField, operator, value]);
        }
    }
    // NB: a field absent from the record reads as `undefined` here (NOT coalesced
    // to False). On the server every field exists and unset reads as False, but on
    // the client an absent field usually means "not loaded" rather than "false",
    // and coalescing would break the invariant that `contains` agrees with
    // expressionFromTree (which does not coalesce free variables).
    const fieldValue = typeof field === "number" ? field : record[field];
    // The server lowercases operators (ast.py). Do the same once so that
    // ["a", "IN", [1]] and other upper/mixed-case operators resolve instead of
    // falling through the case-sensitive switch and throwing.
    const op = typeof operator === "string" ? operator.toLowerCase() : operator;
    const isNot = op.startsWith("not ");
    switch (op) {
        case "=?":
            // Server (optimizations.py): `if not value: return TRUE`. Use
            // truthiness so 0 and "" (not just false/null) are always-true.
            if (!value) {
                return true;
            }
            return matchCondition(record, [field, "=", value]);
        case "=":
        case "==":
            if (Array.isArray(fieldValue) && Array.isArray(value)) {
                return shallowEqual(fieldValue, value);
            }
            if (value === false && Array.isArray(fieldValue)) {
                // Server semantics: ('x2many', '=', False) matches records
                // whose relation is empty.
                return fieldValue.length === 0;
            }
            return fieldValue === value;
        case "!=":
        case "<>":
            return !matchCondition(record, [field, "=", value]);
        case "<":
        case "<=":
        case ">":
        case ">=":
            // An unset field never matches an inequality: SQL comparisons on
            // NULL are falsy server-side, while JS would evaluate
            // `false < 5` as true. Known divergence: a NUMERIC field storing
            // an actual 0 reads as `false` in some client records, so it is
            // excluded here where the server (0, not NULL) would match.
            if (fieldValue === false || fieldValue === undefined) {
                return false;
            }
            switch (op) {
                case "<":
                    return fieldValue < value;
                case "<=":
                    return fieldValue <= value;
                case ">":
                    return fieldValue > value;
                default:
                    return fieldValue >= value;
            }
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
            return new RegExp(likeToRegExp(value)).test(fieldValue) !== isNot;
        }
        case "=like":
        case "not =like":
            if (fieldValue === false) {
                return isNot;
            }
            return (
                new RegExp("^" + likeToRegExp(value) + "$").test(fieldValue) !== isNot
            );
        case "ilike":
        case "not ilike": {
            if (fieldValue === false) {
                return isNot;
            }
            return new RegExp(likeToRegExp(value), "i").test(fieldValue) !== isNot;
        }
        case "=ilike":
        case "not =ilike":
            if (fieldValue === false) {
                return isNot;
            }
            return (
                new RegExp("^" + likeToRegExp(value) + "$", "i").test(fieldValue) !==
                isNot
            );
        case "any":
            // Approximation: `any`/`child_of`/`parent_of` need the related
            // records to evaluate, which contains() does not have, so they
            // always match (see the caveat on Domain.contains). `not any` is
            // defined as the dual of `any` so negation stays consistent: both
            // `!(x any y)` and `x not any y` yield the same result.
            return true;
        case "not any":
            return !matchCondition(record, [field, "any", value]);
        case "child_of":
        case "parent_of":
            // Always-match approximation (see the caveat on Domain.contains):
            // hierarchy resolution needs the related records.
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
        "&": (
            /** @type {Condition | boolean} */ a,
            /** @type {Condition | boolean} */ b,
        ) => match(a) && match(b),
        "|": (
            /** @type {Condition | boolean} */ a,
            /** @type {Condition | boolean} */ b,
        ) => match(a) || match(b),
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
            const arity = OPERATOR_ARITY[item];
            if (condStack.length < arity) {
                throw new InvalidDomainError(
                    `invalid domain (missing operand(s) for "${item}")`,
                );
            }
            const operands = condStack.splice(-arity);
            condStack.push(operator(...operands));
        } else {
            condStack.push(item);
        }
    }
    if (condStack.length !== 1) {
        // Leftover operands mean the prefix expression was malformed; the
        // final pop() would silently evaluate only the first segment.
        throw new InvalidDomainError("invalid domain (unconsumed segment(s))");
    }
    return matchCondition(record, condStack.pop());
}
