/** @odoo-module native */
import { fillEmpty } from "@html_editor/utils/dom";
import {
    containsAnyNonPhrasingContent,
    getDeepestPosition,
    isContentEditable,
    isElement,
    isEmpty,
    isMediaElement,
    isProtected,
    isProtecting,
} from "@html_editor/utils/dom_info";
import { selectElements } from "@html_editor/utils/dom_traversal";
import { childNodeIndex } from "@html_editor/utils/position";
import { withSequence } from "@html_editor/utils/resource";

import { Plugin } from "../plugin.js";
import {
    BASE_CONTAINER_CLASS,
    baseContainerGlobalSelector,
    createBaseContainer,
} from "../utils/base_container.js";

/**
 * @typedef { Object } BaseContainerShared
 * @property { BaseContainerPlugin['createBaseContainer'] } createBaseContainer
 * @property { BaseContainerPlugin['getDefaultNodeName'] } getDefaultNodeName
 * @property { BaseContainerPlugin['isCandidateForBaseContainer'] } isCandidateForBaseContainer
 */

/**
 * @typedef {((node: Node) => boolean)[]} invalid_for_base_container_predicates
 */

export class BaseContainerPlugin extends Plugin {
    static id = "baseContainer";
    static shared = [
        "createBaseContainer",
        "getDefaultNodeName",
        "isCandidateForBaseContainer",
    ];
    static defaultConfig = {
        baseContainers: ["P", "DIV"],
    };
    static dependencies = ["selection"];
    hasNonPhrasingContentPredicate = (element) =>
        element?.nodeType === Node.ELEMENT_NODE &&
        containsAnyNonPhrasingContent(element);
    isUnsplittablePredicate = (element) =>
        this.getResource("unsplittable_node_predicates").some((fn) => fn(element));
    /** @type {import("plugins").EditorResources} */
    resources = {
        clean_for_save_handlers: this.cleanForSave.bind(this),
        normalize_handlers: withSequence(
            Infinity,
            this.normalizeDivBaseContainers.bind(this),
        ),
        delete_handlers: () => {
            if (this.config.cleanEmptyStructuralContainers === false) {
                return;
            }
            this.cleanEmptyStructuralContainers();
        },
        unsplittable_node_predicates: (node) => {
            if (node.nodeName !== "DIV") {
                return false;
            }
            return !this.isCandidateForBaseContainerAllowUnsplittable(node);
        },
        invalid_for_base_container_predicates: [
            (node) =>
                !node ||
                node.nodeType !== Node.ELEMENT_NODE ||
                !this.config.baseContainers.includes(node.tagName) ||
                isProtected(node) ||
                isProtecting(node) ||
                isMediaElement(node),
            this.isUnsplittablePredicate,
            this.hasNonPhrasingContentPredicate,
        ],
        system_classes: [BASE_CONTAINER_CLASS],
    };

    createBaseContainer(nodeName = this.getDefaultNodeName()) {
        return createBaseContainer(nodeName, this.document);
    }

    getDefaultNodeName() {
        return this.config.baseContainers[0];
    }

    cleanEmptyStructuralContainers() {
        const node = this.document.getSelection().anchorNode;

        if (!isElement(node) || !isEmpty(node)) {
            return;
        }

        const closestEditable = (n) =>
            isContentEditable(n.parentElement) ? closestEditable(n.parentElement) : n;

        const isUnsplittable = this.isUnsplittablePredicate(node);
        const isCandidateForBase =
            this.isCandidateForBaseContainerAllowUnsplittable(node);

        if (isUnsplittable || !isCandidateForBase) {
            return;
        }

        let anchorNode = node.parentElement;
        if (
            anchorNode === closestEditable(node) ||
            !this.config.baseContainers.includes(anchorNode.nodeName) ||
            this.getResource("unremovable_node_predicates").some((p) => p(anchorNode))
        ) {
            return;
        }

        if (isEmpty(anchorNode)) {
            fillEmpty(anchorNode);
        }

        let anchorOffset = childNodeIndex(node);
        node.remove();

        [anchorNode, anchorOffset] = getDeepestPosition(anchorNode, anchorOffset);
        this.dependencies.selection.setSelection({
            anchorNode,
            anchorOffset,
        });
    }

    isCandidateForBaseContainer(element) {
        return !this.getResource("invalid_for_base_container_predicates").some((fn) =>
            fn(element),
        );
    }

    isCandidateForBaseContainerAllowUnsplittable(element) {
        for (const predicate of this.getResource(
            "invalid_for_base_container_predicates",
        )) {
            if (predicate === this.isUnsplittablePredicate) {
                continue;
            }
            if (predicate(element)) {
                return false;
            }
        }
        return true;
    }

    shallowIsCandidateForBaseContainer(element) {
        const predicates = this.getResource("invalid_for_base_container_predicates");
        for (const predicate of predicates) {
            if (predicate === this.hasNonPhrasingContentPredicate) {
                continue;
            }
            if (predicate(element)) {
                return false;
            }
        }
        return true;
    }

    cleanForSave({ root }) {
        for (const baseContainer of selectElements(root, `.${BASE_CONTAINER_CLASS}`)) {
            baseContainer.classList.remove(BASE_CONTAINER_CLASS);
            if (baseContainer.classList.length === 0) {
                baseContainer.removeAttribute("class");
            }
        }
    }

    normalizeDivBaseContainers(element = this.editable) {
        if (this.config.baseContainers && !this.config.baseContainers.includes("DIV")) {
            return;
        }
        const newBaseContainers = [];
        const targets = selectElements(element, `div:not(.${BASE_CONTAINER_CLASS})`);
        for (const div of targets) {
            if (
                !div.parentElement?.matches(baseContainerGlobalSelector) &&
                this.shallowIsCandidateForBaseContainer(div) &&
                !containsAnyNonPhrasingContent(div)
            ) {
                div.classList.add(BASE_CONTAINER_CLASS);
                newBaseContainers.push(div);
                if (!div.hasChildNodes()) {
                    const br = document.createElement("br");
                    div.appendChild(br);
                }
            }
        }
    }
}
