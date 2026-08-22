/** @odoo-module native */
import { compareListTypes } from "@html_editor/main/list/utils";
import { withSequence } from "@html_editor/utils/resource";
import {
    normalizeDeepCursorPosition,
    normalizeFakeBR,
} from "@html_editor/utils/selection";
import {
    hasTouch,
    isBrowserChrome,
    isMacOS,
} from "@web/core/browser/feature_detection";

import { Plugin } from "../plugin.js";
import { closestBlock, isBlock } from "../utils/blocks.js";
import { CTYPES } from "../utils/content_types.js";
import {
    isAllowedContent,
    isButton,
    isContentEditable,
    isEmpty,
    isEmptyBlock,
    isInPre,
    isProtected,
    isSelfClosingElement,
    isShrunkBlock,
    isTangible,
    isTextNode,
    isVisibleTextNode,
    isWhitespace,
    isZwnbsp,
    isZWS,
    nextLeaf,
    previousLeaf,
} from "../utils/dom_info.js";
import {
    getState,
    isFakeLineBreak,
    observeMutations,
    prepareUpdate,
} from "../utils/dom_state.js";
import {
    childNodes,
    closestElement,
    descendants,
    findFurthest,
    findUpTo,
    firstLeaf,
    getCommonAncestor,
    lastLeaf,
} from "../utils/dom_traversal.js";
import {
    childNodeIndex,
    DIRECTIONS,
    endPos,
    leftPos,
    nodeSize,
    rightPos,
    startPos,
} from "../utils/position.js";

/**
 * @typedef {Object} RangeLike
 * @property {Node} startContainer
 * @property {number} startOffset
 * @property {Node} endContainer
 * @property {number} endOffset
 */

/** @typedef {import("@html_editor/core/selection_plugin").EditorSelection} EditorSelection */

/**
 * @typedef {Object} DeleteShared
 * @property { DeletePlugin['delete'] } delete
 * @property { DeletePlugin['deleteRange'] } deleteRange
 * @property { DeletePlugin['deleteSelection'] } deleteSelection
 * @property { DeletePlugin['deleteBackward'] } deleteBackward
 * @property { DeletePlugin['deleteForward'] } deleteForward
 */

/**
 * @typedef {(() => void)[]} before_delete_handlers
 * @typedef {(() => void)[]} delete_handlers
 * @typedef {((range: RangeLike) => void | true)[]} delete_backward_overrides
 * @typedef {((range: RangeLike) => void | true)[]} delete_backward_word_overrides
 * @typedef {((range: RangeLike) => void | true)[]} delete_backward_line_overrides
 * @typedef {((range: RangeLike) => void | true)[]} delete_forward_overrides
 * @typedef {((range: RangeLike) => void | true)[]} delete_forward_word_overrides
 * @typedef {((range: RangeLike) => void | true)[]} delete_forward_line_overrides
 * @typedef {((range: RangeLike) => void | true)[]} delete_range_overrides
 * @typedef {((node: Node) => boolean)[]} functional_empty_node_predicates
 * @typedef {((node: Node) => boolean)[]} is_empty_predicates
 * @typedef {((node: Node) => Node[])[]} removable_descendants_providers
 * @typedef {CSSSelector[]} system_node_selectors
 */
/**
 * @typedef {((node: Node, root: HTMLElement) => boolean)[]} unremovable_node_predicates
 */

export const unremovableNodePredicates = [
    (node) => node.classList?.contains("oe_unremovable"),
    (node) => node.matches?.("[data-oe-type='monetary'] > span"),
];

export class DeletePlugin extends Plugin {
    static dependencies = [
        "baseContainer",
        "selection",
        "history",
        "input",
        "userCommand",
    ];
    static id = "delete";
    static shared = [
        "deleteBackward",
        "deleteForward",
        "deleteRange",
        "deleteSelection",
        "delete",
    ];
    /** @type {import("plugins").EditorResources} */
    resources = {
        user_commands: [
            { id: "deleteBackward", run: () => this.delete("backward", "character") },
            { id: "deleteForward", run: () => this.delete("forward", "character") },
            { id: "deleteBackwardWord", run: () => this.delete("backward", "word") },
            { id: "deleteForwardWord", run: () => this.delete("forward", "word") },
            { id: "deleteBackwardLine", run: () => this.delete("backward", "line") },
            { id: "deleteForwardLine", run: () => this.delete("forward", "line") },
        ],
        shortcuts: [
            { hotkey: "backspace", commandId: "deleteBackward" },
            { hotkey: "delete", commandId: "deleteForward" },
            { hotkey: "control+backspace", commandId: "deleteBackwardWord" },
            { hotkey: "control+delete", commandId: "deleteForwardWord" },
            { hotkey: "control+shift+backspace", commandId: "deleteBackwardLine" },
            { hotkey: "control+shift+delete", commandId: "deleteForwardLine" },
        ],
        beforeinput_handlers: [
            withSequence(5, this.onBeforeInputInsertText.bind(this)),
            this.onBeforeInputDelete.bind(this),
        ],
        input_handlers: (ev) => this.onAndroidChromeInput?.(ev),
        selectionchange_handlers: withSequence(5, () =>
            this.onAndroidChromeSelectionChange?.(),
        ),
        delete_backward_overrides: withSequence(
            30,
            this.deleteBackwardUnmergeable.bind(this),
        ),
        delete_backward_word_overrides: withSequence(
            20,
            this.deleteBackwardUnmergeable.bind(this),
        ),
        delete_backward_line_overrides: this.deleteBackwardUnmergeable.bind(this),
        delete_forward_overrides: withSequence(
            20,
            this.deleteForwardUnmergeable.bind(this),
        ),
        delete_forward_word_overrides: this.deleteForwardUnmergeable.bind(this),
        delete_forward_line_overrides: this.deleteForwardUnmergeable.bind(this),

        unremovable_node_predicates: unremovableNodePredicates,
        invalid_for_base_container_predicates: (node) =>
            this.isUnremovable(node, this.editable),
    };

    setup() {
        this.findPreviousPosition = this.makeFindPositionFn("backward");
        this.findNextPosition = this.makeFindPositionFn("forward");
        if (isMacOS()) {
            this.addDomListener(this.editable, "keydown", (event) => {
                const runCommand = (commandId) => {
                    this.dependencies.userCommand.getCommand(commandId).run();
                    event.stopImmediatePropagation();
                    event.preventDefault();
                };
                if (event.altKey && event.key === "Backspace") {
                    return runCommand("deleteBackwardWord");
                }

                if (event.altKey && event.key === "Delete") {
                    return runCommand("deleteForwardWord");
                }

                if (event.metaKey && event.key === "Backspace") {
                    return runCommand("deleteBackwardLine");
                }

                if (event.metaKey && event.key === "Delete") {
                    return runCommand("deleteForwardLine");
                }
            });
        }
    }

    /**
     * @param {EditorSelection} selection
     * @returns {Range}
     */
    getNormalizedRange(selection) {
        let { startContainer, startOffset, endContainer, endOffset, isCollapsed } =
            selection;
        for (const normalizer of [normalizeDeepCursorPosition, normalizeFakeBR]) {
            [startContainer, startOffset] = normalizer(startContainer, startOffset);
            [endContainer, endOffset] = isCollapsed
                ? [startContainer, startOffset]
                : normalizer(endContainer, endOffset);
        }
        const range = this.document.createRange();
        range.setStart(startContainer, startOffset);
        range.setEnd(endContainer, endOffset);
        return range;
    }

    /**
     * @param {EditorSelection} [selection]
     */
    deleteSelection(selection = this.dependencies.selection.getEditableSelection()) {

        let range = this.getNormalizedRange(selection);
        if (range.collapsed) {
            return;
        }
        const selectedNodes = this.dependencies.selection.getTargetedNodes();
        const canBeDeleted = (node) => {
            const isEditableOrFullySelected = (a) =>
                this.dependencies.selection.isNodeEditable(a) ||
                (this.dependencies.selection.areNodeContentsFullySelected(a) &&
                    isContentEditable(a.parentElement));

            return (
                isEditableOrFullySelected(node) ||
                selectedNodes.includes(
                    closestElement(node, (node) => isEditableOrFullySelected(node)),
                )
            );
        };
        if (selectedNodes.some((node) => !canBeDeleted(node))) {
            return;
        }
        range = this.adjustRange(range, [
            this.expandRangeToIncludeNonEditables,
            this.includeEndOrStartBlock,
            this.fullyIncludeLinks,
        ]);

        if (this.delegateTo("delete_range_overrides", range)) {
            return;
        }

        range = this.deleteRange(range);
        this.setCursorFromRange(range);
    }

    /**
     * @param {"backward"|"forward"} direction
     * @param {"character"|"word"|"line"} granularity
     */
    delete(direction, granularity) {
        const selection = this.dependencies.selection.getEditableSelection();

        this.dependencies.history.stageSelection();

        this.dispatchTo("before_delete_handlers");

        if (!selection.isCollapsed) {
            this.deleteSelection(selection);
        } else if (direction === "backward") {
            this.deleteBackward(selection, granularity);
        } else if (direction === "forward") {
            this.deleteForward(selection, granularity);
        } else {
            throw new Error("Invalid direction");
        }
        this.dispatchTo("delete_handlers");
        this.dependencies.history.addStep();
    }

    /**
     * @param {EditorSelection} selection
     * @param {"character"|"word"|"line"} granularity
     */
    deleteBackward(selection, granularity) {
        const { endContainer, endOffset } = this.getNormalizedRange(selection);
        if (!closestElement(endContainer).isContentEditable) {
            return;
        }

        let range = this.getRangeForDelete(
            endContainer,
            endOffset,
            "backward",
            granularity,
        );

        const resourceIds = {
            character: "delete_backward_overrides",
            word: "delete_backward_word_overrides",
            line: "delete_backward_line_overrides",
        };
        if (this.delegateTo(resourceIds[granularity], range)) {
            return;
        }

        range = this.adjustRange(range, [
            this.includeEmptyInlineEnd,
            this.includePreviousZWS,
            this.includeEndOrStartBlock,
        ]);
        range = this.deleteRange(range);
        this.document.getSelection()?.removeAllRanges();
        this.setCursorFromRange(range, { collapseToEnd: true });
    }

    /**
     * @param {EditorSelection} selection
     * @param {"character"|"word"|"line"} granularity
     */
    deleteForward(selection, granularity) {
        const { startContainer, startOffset } = this.getNormalizedRange(selection);
        if (!closestElement(startContainer).isContentEditable) {
            return;
        }

        let range = this.getRangeForDelete(
            startContainer,
            startOffset,
            "forward",
            granularity,
        );

        const resourceIds = {
            character: "delete_forward_overrides",
            word: "delete_forward_word_overrides",
            line: "delete_forward_line_overrides",
        };
        if (this.delegateTo(resourceIds[granularity], range)) {
            return;
        }

        range = this.adjustRange(range, [
            this.includeEmptyInlineStart,
            this.includeNextZWS,
            this.includeEndOrStartBlock,
        ]);
        range = this.deleteRange(range);
        this.setCursorFromRange(range);
    }

    getRangeForDelete(node, offset, direction, granularity) {
        let destContainer, destOffset;
        if (granularity === "word") {
            const blockEl = closestBlock(node);
            if (
                (direction === "backward" &&
                    this.isCursorAtStartOfElement(blockEl, node, offset)) ||
                (direction === "forward" &&
                    this.isCursorAtEndOfElement(blockEl, node, offset))
            ) {
                granularity = "character";
            }
        }
        switch (granularity) {
            case "character":
                [destContainer, destOffset] = this.findAdjacentPosition(
                    node,
                    offset,
                    direction,
                );
                break;
            case "word":
                ({ focusNode: destContainer, focusOffset: destOffset } =
                    this.dependencies.selection.modifySelection(
                        "extend",
                        direction,
                        "word",
                    ));
                break;
            case "line":
                [destContainer, destOffset] = this.findLineBoundary(
                    node,
                    offset,
                    direction,
                );
                break;
            default:
                throw new Error("Invalid granularity");
        }

        if (!destContainer) {
            [destContainer, destOffset] = [node, offset];
        }
        const [startContainer, startOffset, endContainer, endOffset] =
            direction === "forward"
                ? [node, offset, destContainer, destOffset]
                : [destContainer, destOffset, node, offset];

        return { startContainer, startOffset, endContainer, endOffset };
    }


    /**
     * @param {RangeLike} range
     * @returns {RangeLike}
     */
    deleteRange(range) {
        if (
            range.startContainer === range.endContainer &&
            range.startOffset === range.endOffset
        ) {
            return range;
        }
        range = this.splitTextNodes(range);

        const { startContainer, startOffset, endContainer, endOffset } = range;
        const restoreSpaces = prepareUpdate(
            startContainer,
            startOffset,
            endContainer,
            endOffset,
        );

        let restoreFakeBRs;
        ({ restoreFakeBRs, range } = this.removeFakeBRs(range));

        let allNodesRemoved;
        ({ allNodesRemoved, range } = this.removeNodes(range));

        this.fillEmptyInlines(range);

        const originalCommonAncestor = range.commonAncestorContainer;
        if (allNodesRemoved) {
            range = this.joinFragments(range);
        }

        restoreFakeBRs();
        this.fillShrunkBlocks(originalCommonAncestor);
        restoreSpaces();

        return range;
    }

    splitTextNodes({ startContainer, startOffset, endContainer, endOffset }) {
        const split = (textNode, offset) => {
            let didSplit = false;
            if (offset === 0) {
                offset = childNodeIndex(textNode);
            } else if (offset === nodeSize(textNode)) {
                offset = childNodeIndex(textNode) + 1;
            } else {
                textNode.splitText(offset);
                didSplit = true;
                offset = childNodeIndex(textNode) + 1;
            }
            return [textNode.parentElement, offset, didSplit];
        };

        if (endContainer.nodeType === Node.TEXT_NODE) {
            [endContainer, endOffset] = split(endContainer, endOffset);
        }
        if (startContainer.nodeType === Node.TEXT_NODE) {
            let didSplit;
            [startContainer, startOffset, didSplit] = split(
                startContainer,
                startOffset,
            );
            if (startContainer === endContainer && didSplit) {
                endOffset += 1;
            }
        }

        return {
            startContainer,
            startOffset,
            endContainer,
            endOffset,
            commonAncestorContainer: getCommonAncestor(
                [startContainer, endContainer],
                this.editable,
            ),
        };
    }

    removeFakeBRs(range) {
        let {
            startContainer,
            startOffset,
            endContainer,
            endOffset,
            commonAncestorContainer,
        } = range;
        const visitedNodes = new Set();
        const removeBRs = (container, offset) => {
            let node = container;
            while (node !== commonAncestorContainer) {
                const lastBR = childNodes(node).findLast(
                    (child) => child.nodeName === "BR",
                );
                if (lastBR && isFakeLineBreak(lastBR)) {
                    if (lastBR === container) {
                        [container, offset] = leftPos(lastBR);
                    } else if (node === container && offset > childNodeIndex(lastBR)) {
                        offset -= 1;
                    }
                    lastBR.remove();
                }
                visitedNodes.add(node);
                node = node.parentNode;
            }
            return [container, offset];
        };
        [startContainer, startOffset] = removeBRs(startContainer, startOffset);
        [endContainer, endOffset] = removeBRs(endContainer, endOffset);
        range = {
            startContainer,
            startOffset,
            endContainer,
            endOffset,
            commonAncestorContainer,
        };

        const restoreFakeBRs = () => {
            for (const node of visitedNodes) {
                if (!node.isConnected) {
                    continue;
                }
                const lastBR = childNodes(node).findLast(
                    (child) => child.nodeName === "BR",
                );
                if (lastBR && isFakeLineBreak(lastBR)) {
                    lastBR.after(this.document.createElement("br"));
                }
            }
        };

        return { restoreFakeBRs, range };
    }

    fillEmptyInlines(range) {
        const nodes = [range.startContainer];
        if (range.endContainer !== range.startContainer) {
            nodes.push(range.endContainer);
        }
        for (const node of nodes) {
            if (
                !isBlock(node) &&
                !isTangible(node) &&
                !isZWS(node) &&
                !isZwnbsp(node)
            ) {
                node.appendChild(this.document.createTextNode("\u200B"));
                node.setAttribute("data-oe-zws-empty-inline", "");
            }
        }
    }

    fillShrunkBlocks(commonAncestor) {
        const fillBlock = (block) => {
            if (
                block.matches("div[contenteditable='true']") &&
                !block.parentElement.isContentEditable
            ) {
                const baseContainer =
                    this.dependencies.baseContainer.createBaseContainer();
                baseContainer.appendChild(this.document.createElement("br"));
                block.appendChild(baseContainer);
            } else {
                block.appendChild(this.document.createElement("br"));
            }
        };
        for (const node of descendants(commonAncestor).reverse()) {
            if (isBlock(node) && isShrunkBlock(node)) {
                fillBlock(node);
            }
        }
        const containingBlock = closestBlock(commonAncestor);
        if (isShrunkBlock(containingBlock)) {
            fillBlock(containingBlock);
        }
    }

    removeNodes(range) {
        const { startContainer, startOffset, endContainer, commonAncestorContainer } =
            range;
        let { endOffset } = range;
        const nodesToRemove = [];

        let node = startContainer;
        let startRemoveIndex = startOffset;
        while (node !== commonAncestorContainer) {
            for (let i = startRemoveIndex; i < node.childNodes.length; i++) {
                nodesToRemove.push(node.childNodes[i]);
            }
            startRemoveIndex = childNodeIndex(node) + 1;
            node = node.parentElement;
        }

        node = endContainer;
        let endRemoveIndex = endOffset;
        while (node !== commonAncestorContainer) {
            for (let i = 0; i < endRemoveIndex; i++) {
                nodesToRemove.push(node.childNodes[i]);
            }
            endRemoveIndex = childNodeIndex(node);
            node = node.parentElement;
        }

        for (let i = startRemoveIndex; i < endRemoveIndex; i++) {
            nodesToRemove.push(commonAncestorContainer.childNodes[i]);
        }

        let allNodesRemoved = true;
        for (const node of nodesToRemove) {
            const parent = node.parentNode;
            const didRemove = this.removeNode(node);
            allNodesRemoved &&= didRemove;
            if (didRemove && endContainer === parent) {
                endOffset -= 1;
            }
        }

        const endContainerList = closestElement(endContainer, "UL, OL");
        if (
            ["OL", "UL"].includes(startContainer.nodeName) &&
            endContainerList &&
            !compareListTypes(startContainer, endContainerList)
        ) {
            const newRange = this.document.createRange();
            newRange.setStart(range.endContainer, endOffset);
            return { allNodesRemoved, range: newRange };
        }
        return { allNodesRemoved, range: { ...range, endOffset } };
    }

    isUnremovable(node, root = undefined) {
        return this.getResource("unremovable_node_predicates").some((p) =>
            p(node, root),
        );
    }

    removeNode(node) {
        const root = node;
        const remove = (node) => {
            let customHandling = false;
            let customIsUnremovable;
            for (const cb of this.getResource("removable_descendants_providers")) {
                const descendantsToRemove = cb(node);
                if (descendantsToRemove) {
                    for (const descendant of descendantsToRemove) {
                        remove(descendant);
                    }
                    customHandling = true;
                    customIsUnremovable = this.isUnremovable(node, root);
                    if (!customIsUnremovable) {
                        node.remove();
                    }
                }
            }
            if (customHandling) {
                return !customIsUnremovable;
            }
            for (const child of [...node.childNodes]) {
                remove(child);
            }
            if (
                this.isUnremovable(node, root) ||
                (!this.dependencies.selection.isNodeEditable(node) &&
                    !node.parentElement?.isContentEditable)
            ) {
                return false;
            }
            if (node.hasChildNodes() && node.isContentEditable) {
                node.before(...node.childNodes);
                node.remove();
                return false;
            }
            node.remove();
            return true;
        };
        return remove(node);
    }

    joinFragments(range) {
        const joinableLeft = this.getJoinableFragment(range, "start");
        const joinableRight = this.getJoinableFragment(range, "end");
        const join = this.getJoinOperation(joinableLeft.type, joinableRight.type);

        const didJoin = join(
            joinableLeft.node,
            joinableRight.node,
            range.commonAncestorContainer,
        );

        return didJoin ? this.collapseRange(range) : range;
    }

    /**
     * @param {Object} range
     * @param {"start"|"end"} side
     * @returns {Object}
     */
    getJoinableFragment(range, side) {
        const commonAncestor = range.commonAncestorContainer;
        const container = side === "start" ? range.startContainer : range.endContainer;
        const offset = side === "start" ? range.startOffset : range.endOffset;

        if (container === range.commonAncestorContainer) {
            const sibling =
                childNodes(commonAncestor)[side === "start" ? offset - 1 : offset];
            if (
                sibling &&
                !isBlock(sibling) &&
                !(sibling.nodeType === Node.TEXT_NODE && !isVisibleTextNode(sibling))
            ) {
                return { node: sibling, type: "inline" };
            }
            return { node: null, type: "null" };
        }
        let last;
        let element = container;
        while (element !== commonAncestor) {
            if (isBlock(element)) {
                return { node: element, type: "block" };
            }
            last = element;
            element = element.parentElement;
        }
        return { node: last, type: "inline" };
    }

    getJoinOperation(leftType, rightType) {
        return (
            {
                "block + block": this.joinBlocks,
                "block + inline": this.joinInlineIntoBlock,
                "inline + block": this.joinBlockIntoInline,
            }[leftType + " + " + rightType] || (() => true)
        ).bind(this);
    }

    isUnmergeable(node) {
        return this.getResource("unsplittable_node_predicates").some((p) => p(node));
    }

    joinBlocks(left, right, commonAncestor) {
        const canMerge = (n) =>
            !findUpTo(n, commonAncestor, this.isUnmergeable.bind(this));
        if (!canMerge(left) || !canMerge(right)) {
            return false;
        }

        const rightChildNodes = childNodes(right);
        if (!isAllowedContent(left, rightChildNodes)) {
            return false;
        }

        left.append(...rightChildNodes);
        let toRemove = right;
        let parent = right.parentElement;
        while (parent !== commonAncestor && parent.childNodes.length === 1) {
            toRemove = parent;
            parent = parent.parentElement;
        }
        toRemove.remove();
        return true;
    }

    joinInlineIntoBlock(leftBlock, rightInline, commonAncestor) {
        if (findUpTo(leftBlock, commonAncestor, (node) => this.isUnmergeable(node))) {
            return false;
        }

        while (rightInline && !isBlock(rightInline)) {
            const toAppend = rightInline;
            rightInline = rightInline.nextSibling;
            leftBlock.append(toAppend);
        }
        return true;
    }

    joinBlockIntoInline(leftInline, rightBlock, commonAncestor) {
        if (findUpTo(rightBlock, commonAncestor, (node) => this.isUnmergeable(node))) {
            return false;
        }

        leftInline.after(...childNodes(rightBlock));
        let toRemove = rightBlock;
        let parent = rightBlock.parentElement;
        while (parent !== commonAncestor && parent.childNodes.length === 1) {
            toRemove = parent;
            parent = parent.parentElement;
        }
        if (parent === commonAncestor) {
            const rightSibling = toRemove.nextSibling;
            if (rightSibling && !isBlock(rightSibling)) {
                rightSibling.before(this.document.createElement("br"));
            }
        }
        toRemove.remove();
        return true;
    }

    /**
     * @param {RangeLike} range
     * @param {((range: Range) => Range)[]} callbacks
     * @returns {RangeLike}
     */
    adjustRange({ startContainer, startOffset, endContainer, endOffset }, callbacks) {
        let range = this.document.createRange();
        range.setStart(startContainer, startOffset);
        range.setEnd(endContainer, endOffset);

        for (const callback of callbacks) {
            range = callback.call(this, range);
        }

        ({ startContainer, startOffset, endOffset, endContainer } = range);
        return { startContainer, startOffset, endOffset, endContainer };
    }

    /**
     * @param {HTMLElement} block
     * @param {Range} range
     * @returns {Range}
     */
    includeBlockStart(block, range) {
        const { startContainer, startOffset, commonAncestorContainer } = range;
        if (
            block === commonAncestorContainer ||
            !this.isCursorAtStartOfElement(block, startContainer, startOffset)
        ) {
            return range;
        }
        range.setStartBefore(block);
        return this.includeBlockStart(block.parentNode, range);
    }

    /**
     * @param {HTMLElement} block
     * @param {Range} range
     * @returns {Range}
     */
    includeBlockEnd(block, range) {
        const { startContainer, endContainer, endOffset, commonAncestorContainer } =
            range;
        const startList = closestElement(startContainer, "UL, OL");
        const endList = closestElement(endContainer, "UL, OL");
        if (
            block === commonAncestorContainer ||
            !this.isCursorAtEndOfElement(block, endContainer, endOffset) ||
            (startList &&
                endList &&
                !compareListTypes(startList, endList) &&
                !startList.contains(endList))
        ) {
            return range;
        }
        range.setEndAfter(block);
        return this.includeBlockEnd(block.parentNode, range);
    }

    /**
     * @param {Range} range
     * @returns {Range}
     */
    includeEndOrStartBlock(range) {
        const { startContainer, endContainer, commonAncestorContainer } = range;
        const startBlock = findUpTo(startContainer, commonAncestorContainer, isBlock);
        const endBlock = findUpTo(endContainer, commonAncestorContainer, isBlock);
        if (!startBlock || !endBlock) {
            return range;
        }
        range = this.includeBlockEnd(endBlock, range);
        if (range.endContainer === endContainer) {
            range = this.includeBlockStart(startBlock, range);
        }
        return range;
    }

    /**
     * @param {Range} range
     * @returns {Range}
     */
    fullyIncludeLinks(range) {
        const {
            startContainer,
            startOffset,
            endContainer,
            endOffset,
            commonAncestorContainer,
        } = range;
        const [startLink, endLink] = [startContainer, endContainer].map((container) =>
            findUpTo(
                container,
                commonAncestorContainer,
                (node) => node.nodeName === "A",
            ),
        );
        if (
            startLink &&
            this.isCursorAtStartOfElement(startLink, startContainer, startOffset)
        ) {
            range.setStartBefore(startLink);
        }
        if (endLink && this.isCursorAtEndOfElement(endLink, endContainer, endOffset)) {
            range.setEndAfter(endLink);
        }
        return range;
    }

    /**
     * @param {Range} range
     * @returns {Range}
     */
    includeEmptyInlineStart(range) {
        const element = closestElement(range.startContainer);
        if (element && this.isEmptyInline(element)) {
            range.setStartBefore(element);
        }
        return range;
    }

    /**
     * @param {Range} range
     * @returns {Range}
     */
    includeEmptyInlineEnd(range) {
        const element = closestElement(range.endContainer);
        if (element && this.isEmptyInline(element)) {
            range.setEndAfter(element);
        }
        return range;
    }

    /**
     * @param {Range} range
     * @returns {Range}
     */
    includeNextZWS(range) {
        const { endContainer, endOffset } = range;
        if (
            isTextNode(endContainer) &&
            endContainer.textContent[endOffset] === "\u200B"
        ) {
            range.setEnd(endContainer, endOffset + 1);
        }
        return range;
    }

    /**
     * @param {Range} range
     * @returns {Range}
     */
    includePreviousZWS(range) {
        const { startContainer, startOffset } = range;
        if (
            isTextNode(startContainer) &&
            startContainer.textContent[startOffset - 1] === "\u200B"
        ) {
            range.setStart(startContainer, startOffset - 1);
        }
        return range;
    }

    /**
     * @param {Range} range
     * @returns {Range}
     */
    expandRangeToIncludeNonEditables(range) {
        const {
            startContainer,
            startOffset,
            endContainer,
            endOffset,
            commonAncestorContainer: commonAncestor,
        } = range;
        const isNonEditable = (node) => !isContentEditable(node);
        const startUneditable =
            startOffset === 0 &&
            !previousLeaf(startContainer, closestBlock(startContainer)) &&
            findFurthest(startContainer, commonAncestor, isNonEditable);
        if (startUneditable) {
            range.setStartBefore(startUneditable);
        }
        const endUneditable =
            endOffset === nodeSize(endContainer) &&
            !nextLeaf(endContainer, closestBlock(endContainer)) &&
            findFurthest(endContainer, commonAncestor, isNonEditable);
        if (endUneditable) {
            range.setEndAfter(endUneditable);
        }
        return range;
    }

    /**
     * @param {Node} node
     * @param {number} offset
     * @param {"forward"|"backward"} direction
     * @returns {[Node|null, Number|null]}
     */
    findAdjacentPosition(node, offset, direction) {
        return direction === "forward"
            ? this.findNextPosition(node, offset)
            : this.findPreviousPosition(node, offset);
    }

    /**
     * @param {"forward"|"backward"} direction
     */
    makeFindPositionFn(direction) {
        const isDirectionForward = direction === "forward";

        const findVisibleChar = (
            isDirectionForward ? this.findNextVisibleChar : this.findPreviousVisibleChar
        ).bind(this);
        const charLeftPos = (index, char) => index;
        const charRightPos = (index, char) => index + char.length;
        const indexBeforeChar = isDirectionForward ? charLeftPos : charRightPos;
        const indexAfterChar = isDirectionForward ? charRightPos : charLeftPos;
        const textEdgePos = isDirectionForward ? startPos : endPos;
        const adjacentLeaf = (
            isDirectionForward ? this.nextLeaf : this.previousLeaf
        ).bind(this);
        const adjacentLeafFromPos = (
            isDirectionForward ? this.nextLeafFromPos : this.previousLeafFromPos
        ).bind(this);
        const beforePos = isDirectionForward ? leftPos : rightPos;
        const afterPos = isDirectionForward ? rightPos : leftPos;

        /**
         * @param {Node} node
         * @param {number} offset
         * @returns {[Node|null, Number|null]}
         */
        return function findPosition(node, offset) {
            if (node.nodeType === Node.TEXT_NODE) {
                const [char, index] = findVisibleChar(node, offset);
                if (char) {
                    return [node, indexAfterChar(index, char)];
                }
            }

            const isEditableRoot = (n) =>
                n.isContentEditable && !n.parentNode.isContentEditable;
            const editableRoot = findUpTo(
                node,
                this.editable.parentNode,
                isEditableRoot,
            );

            let blockSwitch;
            const nodeClosestBlock = closestBlock(node);
            let leaf = adjacentLeafFromPos(node, offset, editableRoot);
            while (leaf) {
                const leafClosestBlock = closestBlock(leaf);
                blockSwitch ||= leafClosestBlock !== nodeClosestBlock;

                if (this.shouldSkip(leaf, blockSwitch)) {
                    leaf = adjacentLeaf(leaf, editableRoot);
                    continue;
                }

                if (
                    leaf.nodeType === Node.TEXT_NODE &&
                    !(blockSwitch && isEmptyBlock(leafClosestBlock))
                ) {
                    const [char, index] = findVisibleChar(...textEdgePos(leaf));
                    if (char) {
                        const idx = (blockSwitch ? indexBeforeChar : indexAfterChar)(
                            index,
                            char,
                        );
                        return [leaf, idx];
                    }
                } else if (!leaf.isContentEditable && isBlock(leaf)) {
                    return afterPos(leaf);
                } else {
                    return blockSwitch ? beforePos(leaf) : afterPos(leaf);
                }
                leaf = adjacentLeaf(leaf, editableRoot);
            }
            return [null, null];
        };
    }

    findLineBoundary(container, offset, direction) {
        const adjacentLeaf = direction === "forward" ? nextLeaf : previousLeaf;
        const edgeIndex = (node) => (direction === "forward" ? nodeSize(node) : 0);
        const block = closestBlock(container);
        let last = container;
        let node = adjacentLeaf(container, this.editable);
        while (node && node.nodeName !== "BR" && closestBlock(node) === block) {
            last = node;
            node = adjacentLeaf(node, this.editable);
        }
        if (last === container && offset === edgeIndex(container)) {
            return this.findAdjacentPosition(container, offset, direction);
        }
        return direction === "forward" ? rightPos(last) : leftPos(last);
    }

    isVisibleChar(char, textNode, offset) {
        if (isProtected(textNode)) {
            return true;
        }
        const isEmptyButton = (node) =>
            isButton(node) && /^\ufeff*$/.test(node.textContent);
        if (
            isZwnbsp(textNode) &&
            (isButton(textNode.previousSibling) || isEmptyButton(textNode.nextSibling))
        ) {
            return true;
        }
        if (["\u200B", "\uFEFF"].includes(char)) {
            return false;
        }
        if (!isWhitespace(char) || isInPre(textNode)) {
            return true;
        }

        if (offset) {
            return !isWhitespace(textNode.textContent[offset - char.length]);
        } else if (
            !(getState(...leftPos(textNode), DIRECTIONS.LEFT).cType & CTYPES.CONTENT)
        ) {
            return false;
        }

        const charsToTheRight = textNode.textContent.slice(offset + char.length);
        for (char of charsToTheRight) {
            if (!isWhitespace(char)) {
                return true;
            }
        }
        if (getState(...rightPos(textNode), DIRECTIONS.RIGHT).cType & CTYPES.CONTENT) {
            return true;
        }

        return false;
    }

    shouldSkip(leaf, blockSwitch) {
        const systemNodeSelectors = this.getResource("system_node_selectors").join(",");
        if (systemNodeSelectors && closestElement(leaf, systemNodeSelectors)) {
            return true;
        }
        if (leaf.nodeType === Node.TEXT_NODE) {
            return false;
        }
        if (blockSwitch) {
            return false;
        }
        if (leaf.nodeName === "BR" && isFakeLineBreak(leaf)) {
            return true;
        }
        if (
            this.getResource("functional_empty_node_predicates").some((predicate) =>
                predicate(leaf),
            )
        ) {
            return false;
        }
        if (isEmpty(leaf) || isZWS(leaf)) {
            return true;
        }
        return false;
    }

    findPreviousVisibleChar(textNode, index) {
        const chars = [...textNode.textContent.slice(0, index)];
        let char = chars.pop();
        while (char) {
            index -= char.length;
            if (this.isVisibleChar(char, textNode, index)) {
                return [char, index];
            }
            char = chars.pop();
        }
        return [null, null];
    }

    findNextVisibleChar(textNode, index) {
        for (const char of textNode.textContent.slice(index)) {
            if (this.isVisibleChar(char, textNode, index)) {
                return [char, index];
            }
            index += char.length;
        }
        return [null, null];
    }

    adjustedLeaf(leaf, refEditableRoot) {
        const isNonEditable = (node) => !isContentEditable(node);
        const nonEditableRoot =
            leaf && findFurthest(leaf, refEditableRoot, isNonEditable);
        return nonEditableRoot || leaf;
    }

    previousLeaf(node, editableRoot) {
        return this.adjustedLeaf(previousLeaf(node, editableRoot), editableRoot);
    }

    nextLeaf(node, editableRoot) {
        return this.adjustedLeaf(nextLeaf(node, editableRoot), editableRoot);
    }

    previousLeafFromPos(node, offset, editableRoot) {
        const leaf =
            node.hasChildNodes() && offset > 0
                ? lastLeaf(node.childNodes[offset - 1])
                : previousLeaf(node, editableRoot);
        return this.adjustedLeaf(leaf, editableRoot);
    }

    nextLeafFromPos(node, offset, editableRoot) {
        const leaf =
            node.hasChildNodes() && offset < nodeSize(node)
                ? firstLeaf(node.childNodes[offset])
                : nextLeaf(node, editableRoot);
        return this.adjustedLeaf(leaf, editableRoot);
    }

    onBeforeInputDelete(ev) {
        const handledInputTypes = {
            deleteContentBackward: ["backward", "character"],
            deleteContentForward: ["forward", "character"],
            deleteWordBackward: ["backward", "word"],
            deleteWordForward: ["forward", "word"],
            deleteHardLineBackward: ["backward", "line"],
            deleteHardLineForward: ["forward", "line"],
        };
        const argsForDelete = handledInputTypes[ev.inputType];
        if (argsForDelete) {
            this.delete(...argsForDelete);
            ev.preventDefault();
            if (isBrowserChrome() && hasTouch()) {
                this.preventDefaultDeleteAndroidChrome(ev);
            }
        }
    }

    onBeforeInputInsertText(ev) {
        if (ev.inputType === "insertText") {
            const selection =
                this.dependencies.selection.getSelectionData().deepEditableSelection;
            if (!selection.isCollapsed) {
                this.dispatchTo("before_delete_handlers");
                this.deleteSelection(selection);
                this.dispatchTo("delete_handlers");
            }
        }
    }

    /**
     * @param {InputEvent} beforeInputEvent
     */
    preventDefaultDeleteAndroidChrome(beforeInputEvent) {
        const restoreDOM = this.dependencies.history.makeSavePoint();
        this.onAndroidChromeInput = (ev) => {
            if (ev.inputType !== beforeInputEvent.inputType) {
                return;
            }
            restoreDOM();

            const { restore: restoreSelection } =
                this.dependencies.selection.preserveSelection();
            const observerOptions = {
                childList: true,
                subtree: true,
                characterData: true,
            };
            const getMutationRecords = observeMutations(this.editable, observerOptions);
            this.onAndroidChromeSelectionChange = () => {
                const shouldRevertSelectionChanges = !getMutationRecords().length;
                if (shouldRevertSelectionChanges) {
                    restoreSelection();
                }
            };
            setTimeout(() => delete this.onAndroidChromeSelectionChange);
        };
    }

    deleteBackwardUnmergeable(range) {
        const { startContainer, startOffset, endContainer, endOffset } = range;
        return this.deleteCharUnmergeable(
            endContainer,
            endOffset,
            startContainer,
            startOffset,
        );
    }

    deleteForwardUnmergeable(range) {
        const { startContainer, startOffset, endContainer, endOffset } = range;
        return this.deleteCharUnmergeable(
            startContainer,
            startOffset,
            endContainer,
            endOffset,
        );
    }

    deleteCharUnmergeable(sourceContainer, sourceOffset, destContainer, destOffset) {
        if (!destContainer) {
            return;
        }
        const commonAncestor = getCommonAncestor(
            [sourceContainer, destContainer],
            this.editable,
        );
        const closestUnmergeable = findUpTo(sourceContainer, commonAncestor, (node) =>
            this.isUnmergeable(node),
        );
        if (!closestUnmergeable) {
            return;
        }

        if (
            (isEmpty(closestUnmergeable) ||
                this.getResource("is_empty_predicates").some((p) =>
                    p(closestUnmergeable),
                )) &&
            !this.isUnremovable(closestUnmergeable)
        ) {
            closestUnmergeable.remove();
            this.fillShrunkBlocks(commonAncestor);
            this.dependencies.selection.setSelection({
                anchorNode: destContainer,
                anchorOffset: destOffset,
            });
        } else {
            this.dependencies.selection.setSelection({
                anchorNode: sourceContainer,
                anchorOffset: sourceOffset,
            });
        }
        return true;
    }

    isEmptyInline(element) {
        if (isBlock(element)) {
            return false;
        }
        if (isZWS(element)) {
            return true;
        }
        return element.innerHTML.trim() === "";
    }

    isCursorAtStartOfElement(element, cursorNode, cursorOffset) {
        const [node] = this.findPreviousPosition(cursorNode, cursorOffset);
        return !element.contains(node);
    }

    isCursorAtEndOfElement(element, cursorNode, cursorOffset) {
        const [node] = this.findNextPosition(cursorNode, cursorOffset);
        return !element.contains(node);
    }

    /**
     * @param {RangeLike} range
     */
    setCursorFromRange(range, { collapseToEnd = false } = {}) {
        range = this.collapseRange(range, { toEnd: collapseToEnd });
        const [anchorNode, anchorOffset] = this.normalizeEnterBlock(
            range.startContainer,
            range.startOffset,
        );
        this.dependencies.selection.setSelection({ anchorNode, anchorOffset });
    }

    normalizeEnterBlock(node, offset) {
        while (
            isBlock(node.childNodes[offset]) &&
            !isSelfClosingElement(node.childNodes[offset])
        ) {
            [node, offset] = [node.childNodes[offset], 0];
        }
        return [node, offset];
    }

    /**
     * @param {RangeLike} range
     */
    collapseRange(range, { toEnd = false } = {}) {
        let { startContainer, startOffset, endContainer, endOffset } = range;
        if (toEnd) {
            [startContainer, startOffset] = [endContainer, endOffset];
        } else {
            [endContainer, endOffset] = [startContainer, startOffset];
        }
        const commonAncestorContainer = startContainer;
        return {
            startContainer,
            startOffset,
            endContainer,
            endOffset,
            commonAncestorContainer,
        };
    }
}
