/** @odoo-module native */
/* eslint-disable no-console -- opt-in debug logging (gated on options.debug) */
import { isBlock } from "./blocks.js";
import { CTGROUPS, CTYPES, ctypeToString } from "./content_types.js";
import { isInPre, isVisible, isWhitespace, whitespace } from "./dom_info.js";
import {
    ancestors,
    closestElement,
    closestPath,
    createDOMPathGenerator,
    PATH_END_REASONS,
} from "./dom_traversal.js";
import { DIRECTIONS, leftPos, rightPos } from "./position.js";

const prepareUpdateLockedEditables = new Set();
/**
 * @param {HTMLElement} el
 * @param {number} offset
 * @param {...(HTMLElement|number)} args
 * @param {Object} [options]
 * @param {boolean} [options.allowReenter = true]
 * @param {string} [options.label = <random 6 character string>]
 * @param {boolean} [options.debug = false]
 * @returns {function}
 */
export function prepareUpdate(...args) {
    const closestRoot =
        args.length &&
        ancestors(args[0]).find((ancestor) =>
            ancestor.classList.contains("odoo-editor-editable"),
        );
    const isPrepareUpdateLocked =
        closestRoot && prepareUpdateLockedEditables.has(closestRoot);
    const hash = (Math.random() + 1).toString(36).substring(7);
    const options = {
        allowReenter: true,
        label: hash,
        debug: false,
        ...(args.length && args[args.length - 1] instanceof Object ? args.pop() : {}),
    };
    if (options.debug) {
        console.log(
            "%cPreparing%c update: " +
                options.label +
                (options.label === hash ? "" : ` (${hash})`) +
                "%c" +
                (isPrepareUpdateLocked ? " LOCKED" : ""),
            "color: cyan;",
            "color: white;",
            "color: red; font-weight: bold;",
        );
    }
    if (isPrepareUpdateLocked) {
        return () => {
            if (options.debug) {
                console.log(
                    "%cRestoring%c update: " +
                        options.label +
                        (options.label === hash ? "" : ` (${hash})`) +
                        "%c LOCKED",
                    "color: lightgreen;",
                    "color: white;",
                    "color: red; font-weight: bold;",
                );
            }
        };
    }
    if (!options.allowReenter && closestRoot) {
        prepareUpdateLockedEditables.add(closestRoot);
    }
    const positions = [...args];

    const restoreData = [];
    let el, offset;
    while (positions.length) {
        offset = positions.pop();
        el = positions.pop();
        const left = getState(el, offset, DIRECTIONS.LEFT);
        const right = getState(el, offset, DIRECTIONS.RIGHT, left.cType);
        if (options.debug) {
            const editable = el && closestElement(el, ".odoo-editor-editable");
            const oldEditableHTML =
                (editable &&
                    editable.innerHTML
                        .replaceAll(" ", "_")
                        .replaceAll("\u200B", "ZWS")) ||
                "";
            left.oldEditableHTML = oldEditableHTML;
            right.oldEditableHTML = oldEditableHTML;
        }
        restoreData.push(left, right);
    }

    return function restoreStates() {
        if (options.debug) {
            console.log(
                "%cRestoring%c update: " +
                    options.label +
                    (options.label === hash ? "" : ` (${hash})`),
                "color: lightgreen;",
                "color: white;",
            );
        }
        for (const data of restoreData) {
            restoreState(data, options.debug);
        }
        if (!options.allowReenter && closestRoot) {
            prepareUpdateLockedEditables.delete(closestRoot);
        }
    };
}

export const leftLeafOnlyNotBlockPath = createDOMPathGenerator(DIRECTIONS.LEFT, {
    leafOnly: true,
    stopTraverseFunction: isBlock,
    stopFunction: isBlock,
});

const rightLeafOnlyNotBlockPath = createDOMPathGenerator(DIRECTIONS.RIGHT, {
    leafOnly: true,
    stopTraverseFunction: isBlock,
    stopFunction: isBlock,
});

/**
 * @param {HTMLElement} el
 * @param {number} offset
 * @param {boolean} direction
 * @param {CTYPES} [leftCType]
 * @returns {Object}
 */
export function getState(el, offset, direction, leftCType) {
    const leftDOMPath = leftLeafOnlyNotBlockPath;
    const rightDOMPath = rightLeafOnlyNotBlockPath;

    let domPath;
    let inverseDOMPath;
    const whitespaceAtStartRegex = new RegExp("^" + whitespace + "+");
    const whitespaceAtEndRegex = new RegExp(whitespace + "+$");
    const reasons = [];
    if (direction === DIRECTIONS.LEFT) {
        domPath = leftDOMPath(el, offset, reasons);
        inverseDOMPath = rightDOMPath(el, offset);
    } else {
        domPath = rightDOMPath(el, offset, reasons);
        inverseDOMPath = leftDOMPath(el, offset);
    }

    const boundaryNode = inverseDOMPath.next().value;

    let cType = undefined;

    let lastSpace = null;
    for (const node of domPath) {
        if (node.nodeType === Node.TEXT_NODE) {
            const value = node.nodeValue;
            if (direction === DIRECTIONS.LEFT) {
                if (!isWhitespace(value)) {
                    if (lastSpace) {
                        cType = CTYPES.SPACE;
                    } else {
                        const rightLeaf = rightLeafOnlyNotBlockPath(node).next().value;
                        const hasContentRight =
                            rightLeaf &&
                            !whitespaceAtStartRegex.test(rightLeaf.textContent);
                        cType =
                            !hasContentRight &&
                            whitespaceAtEndRegex.test(node.textContent)
                                ? CTYPES.SPACE
                                : CTYPES.CONTENT;
                    }
                    break;
                }
                if (value.length) {
                    lastSpace = node;
                }
            } else {
                leftCType = leftCType || getState(el, offset, DIRECTIONS.LEFT).cType;
                if (whitespaceAtStartRegex.test(value)) {
                    const leftLeaf = leftLeafOnlyNotBlockPath(node).next().value;
                    const hasContentLeft =
                        leftLeaf && !whitespaceAtEndRegex.test(leftLeaf.textContent);
                    const rct = !isWhitespace(value)
                        ? CTYPES.CONTENT
                        : getState(...rightPos(node), DIRECTIONS.RIGHT).cType;
                    cType =
                        leftCType & CTYPES.CONTENT &&
                        rct & (CTYPES.CONTENT | CTYPES.BR) &&
                        !hasContentLeft
                            ? CTYPES.SPACE
                            : rct;
                    break;
                }
                if (!isWhitespace(value)) {
                    cType = CTYPES.CONTENT;
                    break;
                }
            }
        } else if (node.nodeName === "BR") {
            cType = CTYPES.BR;
            break;
        } else if (isVisible(node)) {
            cType = CTYPES.CONTENT;
            break;
        }
    }

    if (cType === undefined) {
        cType = reasons.includes(PATH_END_REASONS.BLOCK_HIT)
            ? CTYPES.BLOCK_OUTSIDE
            : CTYPES.BLOCK_INSIDE;
    }

    return {
        node: boundaryNode,
        direction: direction,
        cType: cType,
    };
}
const priorityRestoreStateRules = [
    [
        { cType1: CTYPES.CONTENT, cType2: CTYPES.SPACE | CTGROUPS.BLOCK },
        { spaceVisibility: true },
    ],
    [
        { direction: DIRECTIONS.LEFT, cType1: CTGROUPS.INLINE, cType2: CTGROUPS.BR },
        { spaceVisibility: true },
    ],
    [
        { direction: DIRECTIONS.RIGHT, cType1: CTGROUPS.CONTENT, cType2: CTGROUPS.BR },
        { spaceVisibility: true },
    ],
    [
        { direction: DIRECTIONS.RIGHT, cType1: CTGROUPS.BR, cType2: CTYPES.SPACE },
        { spaceVisibility: true },
    ],
    [
        { direction: DIRECTIONS.RIGHT, cType1: CTGROUPS.BR, cType2: CTGROUPS.BLOCK },
        { spaceVisibility: true, brVisibility: true },
    ],
    [
        { cType1: CTYPES.SPACE },
        { spaceVisibility: false },
    ],
    [
        { direction: DIRECTIONS.LEFT, cType1: CTGROUPS.BR },
        { spaceVisibility: false },
    ],
    [
        { cType1: CTGROUPS.BLOCK, cType2: CTGROUPS.INLINE | CTGROUPS.BR },
        { spaceVisibility: false },
    ],
    [
        {
            direction: DIRECTIONS.RIGHT,
            cType1: CTGROUPS.INLINE,
            cType2: CTGROUPS.BLOCK,
        },
        { brVisibility: true },
    ],
    [
        {
            direction: DIRECTIONS.RIGHT,
            cType1: CTGROUPS.BLOCK,
            cType2: CTGROUPS.INLINE | CTGROUPS.BR,
        },
        { brVisibility: false },
    ],
    [
        {
            direction: DIRECTIONS.LEFT,
            cType1: CTGROUPS.BR | CTGROUPS.BLOCK,
            cType2: CTGROUPS.INLINE,
        },
        {
            brVisibility: false,
            extraBRRemovalCondition: (brNode) => isFakeLineBreak(brNode),
        },
    ],
];
function restoreStateRuleHashCode(direction, cType1, cType2) {
    return `${direction}-${cType1}-${cType2}`;
}
const allRestoreStateRules = (function () {
    const map = new Map();

    const keys = ["direction", "cType1", "cType2"];
    for (const direction of Object.values(DIRECTIONS)) {
        for (const cType1 of Object.values(CTYPES)) {
            for (const cType2 of Object.values(CTYPES)) {
                const rule = { direction: direction, cType1: cType1, cType2: cType2 };

                const matchedRules = [];
                for (const entry of priorityRestoreStateRules) {
                    let priority = 0;
                    for (const key of keys) {
                        const entryKeyValue = entry[0][key];
                        if (entryKeyValue !== undefined) {
                            if (
                                typeof entryKeyValue === "boolean"
                                    ? rule[key] === entryKeyValue
                                    : rule[key] & entryKeyValue
                            ) {
                                priority++;
                            } else {
                                priority = -1;
                                break;
                            }
                        }
                    }
                    if (priority >= 0) {
                        matchedRules.push([priority, entry[1]]);
                    }
                }

                const finalRule = {};
                for (let p = 0; p <= keys.length; p++) {
                    for (const entry of matchedRules) {
                        if (entry[0] === p) {
                            Object.assign(finalRule, entry[1]);
                        }
                    }
                }

                const hashCode = restoreStateRuleHashCode(direction, cType1, cType2);
                map.set(hashCode, finalRule);
            }
        }
    }

    return map;
})();
/**
 * @param {Object} prevStateData
 * @param {boolean} debug=false
 * @returns {Object|undefined}
 */
export function restoreState(prevStateData, debug = false) {
    const { node, direction, cType: cType1, oldEditableHTML } = prevStateData;
    if (!node || !node.parentNode) {
        return;
    }
    const [el, offset] = direction === DIRECTIONS.LEFT ? leftPos(node) : rightPos(node);
    const { cType: cType2 } = getState(el, offset, direction);

    const ruleHashCode = restoreStateRuleHashCode(direction, cType1, cType2);
    const rule = allRestoreStateRules.get(ruleHashCode);
    if (debug) {
        const editable = closestElement(node, ".odoo-editor-editable");
        console.log(
            "%c" +
                node.textContent.replaceAll(" ", "_").replaceAll("\u200B", "ZWS") +
                "\n" +
                "%c" +
                (direction === DIRECTIONS.LEFT ? "left" : "right") +
                "\n" +
                "%c" +
                ctypeToString(cType1) +
                "\n" +
                "%c" +
                ctypeToString(cType2) +
                "\n" +
                "%c" +
                "BEFORE: " +
                (oldEditableHTML || "(unavailable)") +
                "\n" +
                "%c" +
                "AFTER:  " +
                (editable
                    ? editable.innerHTML
                          .replaceAll(" ", "_")
                          .replaceAll("\u200B", "ZWS")
                    : "(unavailable)") +
                "\n",
            "color: white; display: block; width: 100%;",
            "color: " +
                (direction === DIRECTIONS.LEFT ? "magenta" : "lightgreen") +
                "; display: block; width: 100%;",
            "color: pink; display: block; width: 100%;",
            "color: lightblue; display: block; width: 100%;",
            "color: white; display: block; width: 100%;",
            "color: white; display: block; width: 100%;",
            rule,
        );
    }
    if (Object.values(rule).filter((x) => x !== undefined).length) {
        const inverseDirection =
            direction === DIRECTIONS.LEFT ? DIRECTIONS.RIGHT : DIRECTIONS.LEFT;
        enforceWhitespace(el, offset, inverseDirection, rule);
    }
    return rule;
}

/**
 * @param {HTMLBRElement} brEl
 * @returns {boolean}
 */
export function isFakeLineBreak(brEl) {
    return !(
        getState(...rightPos(brEl), DIRECTIONS.RIGHT).cType &
        (CTYPES.CONTENT | CTGROUPS.BR)
    );
}

/**
 * @param {HTMLElement} el
 * @param {number} offset
 * @param {number} direction
 * @param {Object} rule
 * @param {boolean} [rule.spaceVisibility]
 * @param {boolean} [rule.brVisibility]
 */
export function enforceWhitespace(el, offset, direction, rule) {
    const document = el.ownerDocument;
    let domPath, whitespaceAtEdgeRegex;
    if (direction === DIRECTIONS.LEFT) {
        domPath = leftLeafOnlyNotBlockPath(el, offset);
        whitespaceAtEdgeRegex = new RegExp(whitespace + "+$");
    } else {
        domPath = rightLeafOnlyNotBlockPath(el, offset);
        whitespaceAtEdgeRegex = new RegExp("^" + whitespace + "+");
    }

    const invisibleSpaceTextNodes = [];
    let foundVisibleSpaceTextNode = null;
    for (const node of domPath) {
        if (node.nodeName === "BR") {
            if (rule.brVisibility === undefined) {
                break;
            }
            if (rule.brVisibility) {
                node.before(document.createElement("br"));
            } else {
                if (
                    !rule.extraBRRemovalCondition ||
                    rule.extraBRRemovalCondition(node)
                ) {
                    node.remove();
                }
            }
            break;
        } else if (node.nodeType === Node.TEXT_NODE && !isInPre(node)) {
            if (whitespaceAtEdgeRegex.test(node.nodeValue)) {
                if (!isWhitespace(node)) {
                    foundVisibleSpaceTextNode = node;
                    break;
                } else {
                    invisibleSpaceTextNodes.push(node);
                }
            } else if (!isWhitespace(node)) {
                break;
            }
        } else {
            break;
        }
    }

    if (rule.spaceVisibility === undefined) {
        return;
    }
    if (!rule.spaceVisibility) {
        for (const node of invisibleSpaceTextNodes) {
            node.nodeValue = "";
            const ancestorPath = closestPath(node.parentNode);
            let toRemove = null;
            for (const pNode of ancestorPath) {
                if (toRemove) {
                    toRemove.remove();
                }
                if (pNode.childNodes.length === 1 && !isBlock(pNode)) {
                    pNode.after(node);
                    toRemove = pNode;
                } else {
                    break;
                }
            }
        }
    }
    const spaceNode = foundVisibleSpaceTextNode || invisibleSpaceTextNodes[0];
    if (spaceNode) {
        let spaceVisibility = rule.spaceVisibility;
        if (
            spaceVisibility &&
            !foundVisibleSpaceTextNode &&
            getState(...rightPos(spaceNode), DIRECTIONS.RIGHT).cType & CTGROUPS.BLOCK &&
            getState(...leftPos(spaceNode), DIRECTIONS.LEFT).cType !== CTYPES.CONTENT
        ) {
            spaceVisibility = false;
        }
        spaceNode.nodeValue = spaceNode.nodeValue.replace(
            whitespaceAtEdgeRegex,
            spaceVisibility ? "\u00A0" : "",
        );
    }
}

/**
 * @returns {() => MutationRecord[]}
 */
export function observeMutations(target, observerOptions) {
    const records = [];
    const observerCallback = (mutations) => records.push(...mutations);
    const observer = new MutationObserver(observerCallback);
    observer.observe(target, observerOptions);
    return () => {
        observerCallback(observer.takeRecords());
        observer.disconnect();
        return records;
    };
}
