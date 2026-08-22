/** @odoo-module native */
import { DIRECTIONS } from "./position.js";

export const closestPath = function* (node) {
    while (node) {
        yield node;
        node = node.parentNode;
    }
};

/**
 * @param {Iterable<Node>} domPath
 * @param {Function} [findCallback]
 * @param {Function} [stopCallback]
 * @returns {Node|null}
 */
export function findNode(
    domPath,
    findCallback = () => true,
    stopCallback = () => false,
) {
    for (const node of domPath) {
        if (findCallback(node)) {
            return node;
        }
        if (stopCallback(node)) {
            break;
        }
    }
    return null;
}

/**
 * @param {Node} node
 * @param {HTMLElement} limitAncestor
 * @param {Function} predicate
 * @returns {Node|null}
 */
export function findUpTo(node, limitAncestor, predicate) {
    while (node !== limitAncestor) {
        if (predicate(node)) {
            return node;
        }
        node = node.parentElement;
    }
    return null;
}

/**
 * @param {Node} node
 * @param {HTMLElement} limitAncestor
 * @param {Function} predicate
 * @returns {Node|undefined}
 */
export function findFurthest(node, limitAncestor, predicate) {
    const nodes = [];
    while (node !== limitAncestor) {
        nodes.push(node);
        node = node.parentNode;
    }
    return nodes.findLast(predicate);
}

/**
 * @param {Node} node
 * @param {string | Function} [predicate='*']
 * @returns {HTMLElement|null}
 */
export function closestElement(node, predicate = "*") {
    let element = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
    const editable = element?.closest(".odoo-editor-editable");
    if (typeof predicate === "function") {
        while (element && !predicate(element)) {
            element = element.parentElement;
        }
    } else {
        element = element?.closest(predicate);
    }
    if ((editable && editable.contains(element)) || !node.isConnected) {
        return element || null;
    }
    return null;
}

/**
 * @param {Node} node
 * @param {Node} [editable]
 * @returns {HTMLElement[]}
 */
export function ancestors(node, editable) {
    const result = [];
    while (node && node.parentElement && node !== editable) {
        result.push(node.parentElement);
        node = node.parentElement;
    }
    return result;
}

/**
 * @param {Element} elem
 * @returns {Array<Element>}
 */
export function children(elem) {
    const children = [];
    let child = elem.firstElementChild;
    while (child) {
        children.push(child);
        child = child.nextElementSibling;
    }
    return children;
}

/**
 * @param {Node} node
 * @returns {Array<Node>}
 */
export function childNodes(node) {
    const childNodes = [];
    let child = node.firstChild;
    while (child) {
        childNodes.push(child);
        child = child.nextSibling;
    }
    return childNodes;
}

/**
 * @param {Node} node
 * @returns {Node[]}
 */
export function descendants(node, posterity = []) {
    let child = node.firstChild;
    while (child) {
        posterity.push(child);
        descendants(child, posterity);
        child = child.nextSibling;
    }
    return posterity;
}

export const PATH_END_REASONS = {
    NO_NODE: 0,
    BLOCK_OUT: 1,
    BLOCK_HIT: 2,
    OUT_OF_SCOPE: 3,
};

/**
 * @param {boolean} direction
 * @param {Object} options
 * @param {boolean} [options.leafOnly]
 * @param {boolean} [options.inScope]
 * @param {Function} [options.stopTraverseFunction]
 * @param {Function} [options.stopFunction]
 */
export function createDOMPathGenerator(
    direction,
    { leafOnly = false, inScope = false, stopTraverseFunction, stopFunction } = {},
) {
    const nextDeepest =
        direction === DIRECTIONS.LEFT
            ? (node) => lastLeaf(node.previousSibling, stopTraverseFunction)
            : (node) => firstLeaf(node.nextSibling, stopTraverseFunction);

    const firstNode =
        direction === DIRECTIONS.LEFT
            ? (node, offset) =>
                  lastLeaf(node.childNodes[offset - 1], stopTraverseFunction)
            : (node, offset) =>
                  firstLeaf(node.childNodes[offset], stopTraverseFunction);

    return function* (node, offset, reasons = []) {
        let movedUp = false;

        let currentNode = firstNode(node, offset);
        if (!currentNode) {
            movedUp = true;
            currentNode = node;
        }

        while (currentNode) {
            if (stopFunction && stopFunction(currentNode)) {
                reasons.push(
                    movedUp ? PATH_END_REASONS.BLOCK_OUT : PATH_END_REASONS.BLOCK_HIT,
                );
                break;
            }
            if (inScope && currentNode === node) {
                reasons.push(PATH_END_REASONS.OUT_OF_SCOPE);
                break;
            }
            if (!(leafOnly && movedUp)) {
                yield currentNode;
            }

            movedUp = false;
            let nextNode = nextDeepest(currentNode);
            if (!nextNode) {
                movedUp = true;
                nextNode = currentNode.parentNode;
            }
            currentNode = nextNode;
        }

        reasons.push(PATH_END_REASONS.NO_NODE);
    };
}

/**
 * @param {Node} node
 * @param {Function} [stopTraverseFunction]
 * @returns {Node}
 */
export function lastLeaf(node, stopTraverseFunction) {
    while (
        node &&
        node.lastChild &&
        !(stopTraverseFunction && stopTraverseFunction(node))
    ) {
        node = node.lastChild;
    }
    return node;
}
/**
 * @param {Node} node
 * @param {Function} [stopTraverseFunction]
 * @returns {Node}
 */
export function firstLeaf(node, stopTraverseFunction) {
    while (
        node &&
        node.firstChild &&
        !(stopTraverseFunction && stopTraverseFunction(node))
    ) {
        node = node.firstChild;
    }
    return node;
}

/**
 * @param {Node} node
 * @param {Function} [predicate]
 */
export function getAdjacentPreviousSiblings(node, predicate = (n) => !!n) {
    let previous = node.previousSibling;
    const list = [];
    while (previous && predicate(previous)) {
        list.push(previous);
        previous = previous.previousSibling;
    }
    return list;
}
/**
 * @param {Node} node
 * @param {Function} [predicate]
 */
export function getAdjacentNextSiblings(node, predicate = (n) => !!n) {
    let next = node.nextSibling;
    const list = [];
    while (next && predicate(next)) {
        list.push(next);
        next = next.nextSibling;
    }
    return list;
}
/**
 * @param {Node} node
 * @param {Function} [predicate]
 */
export function getAdjacents(node, predicate = (n) => !!n) {
    const previous = getAdjacentPreviousSiblings(node, predicate);
    const next = getAdjacentNextSiblings(node, predicate);
    return predicate(node) ? [...previous.reverse(), node, ...next] : [];
}

/**
 * @param {Node[]} nodes
 * @param {Element} [root]
 * @returns {Element|null}
 */
export function getCommonAncestor(nodes, root = undefined) {
    const pathsToRoot = nodes.map((node) => [node, ...ancestors(node, root)]);

    let candidate = pathsToRoot[0]?.at(-1);
    if (root && candidate !== root) {
        return null;
    }
    let commonAncestor = null;
    while (candidate && pathsToRoot.every((path) => path.at(-1) === candidate)) {
        commonAncestor = candidate;
        pathsToRoot.forEach((path) => path.pop());
        candidate = pathsToRoot[0].at(-1);
    }
    return commonAncestor;
}

/**
 * @param {Element} root
 * @param {string} selector
 * @returns {Generator<Element>}
 */
export const selectElements = function* (root, selector) {
    if (root.matches(selector)) {
        yield root;
    }
    for (const elem of root.querySelectorAll(selector)) {
        yield elem;
    }
};
