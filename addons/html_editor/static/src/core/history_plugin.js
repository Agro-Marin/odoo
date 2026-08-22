/** @odoo-module native */
import { toggleClass } from "@html_editor/utils/dom";
import { withSequence } from "@html_editor/utils/resource";
import { hasTouch } from "@web/core/browser/feature_detection";
import { _t } from "@web/core/translation";
import { omit, pick } from "@web/core/utils/collections/objects";
import { Deferred } from "@web/core/utils/concurrency";

import { Plugin } from "../plugin.js";
import { childNodes, descendants, getCommonAncestor } from "../utils/dom_traversal.js";
import { generateId } from "../utils/ids.js";
import { trackOccurrences, trackOccurrencesPair } from "../utils/tracking.js";

/**
 * @typedef { import("./selection_plugin").EditorSelection } EditorSelection
 * @typedef { Object } SerializedSelection
 * @property { string } anchorNodeId
 * @property { number } anchorOffset
 * @property { string } focusNodeId
 * @property { number } focusOffset
 * @typedef { Object } SerializedNode
 * @property { number } nodeType
 * @property { string } nodeId
 * @property { string } textValue
 * @property { string } tagName
 * @property { SerializedNode[] } children
 * @property { Record<string, string> } attributes
 * @typedef { Object } HistoryStep
 * @property { string } id
 * @property {"original"|"undo"|"redo"|"restore"} type
 * @property { SerializedSelection } selection
 * @property { HistoryMutation[] } mutations
 * @property { string } previousStepId
 * @property { Object } extraStepInfos
 * @typedef { Object } HistoryMutationCharacterData
 * @property { "characterData" } type
 * @property { string } nodeId
 * @property { string } value
 * @property { string } oldValue
 * @typedef { Object } HistoryMutationAttributes
 * @property { "attributes" } type
 * @property { string } nodeId
 * @property { string } attributeName
 * @property { string } value
 * @property { string } oldValue
 * @typedef { Object } HistoryMutationClassList
 * @property { "classList" } type
 * @property { string } nodeId
 * @property { string } className
 * @property { boolean } value
 * @property { boolean } oldValue
 * @typedef { Object } HistoryMutationAdd
 * @property { "add" } type
 * @property { string } nodeId
 * @property { string } parentNodeId
 * @property { SerializedNode } serializedNode
 * @property { string } nextNodeId
 * @property { string } previousNodeId
 * @typedef { Object } HistoryMutationRemove
 * @property { "remove" } type
 * @property { string } nodeId
 * @property { string } parentNodeId
 * @property { SerializedNode } serializedNode
 * @property { string } nextNodeId
 * @property { string } previousNodeId
 * @typedef { HistoryMutationCharacterData | HistoryMutationAttributes | HistoryMutationClassList | HistoryMutationAdd | HistoryMutationRemove } HistoryMutation
 * @typedef {Object} MutationRecordClassList
 * @property { "classList" } type
 * @property { Node } target
 * @property { string } className
 * @property { boolean } oldValue
 * @property { boolean } value
 * @typedef {Object} MutationRecordAttributes
 * @property { "attributes" } type
 * @property { Node } target
 * @property { string } attributeName
 * @property { string } oldValue
 * @property { string } value
 * @typedef {Object} MutationRecordCharacterData
 * @property { "characterData" } type
 * @property { Node } target
 * @property { string } oldValue
 * @property { string } value
 * @typedef {Object} Tree
 * @property {Node} node
 * @property {Tree[]} children
 * @typedef {Object} MutationRecordChildList
 * @property { "childList" } type
 * @property { Node } target
 * @property { Node } previousSibling
 * @property { Node } nextSibling
 * @property { Tree[] } addedTrees
 * @property { Tree[] } removedTrees
 * @typedef { MutationRecordClassList | MutationRecordAttributes | MutationRecordCharacterData | MutationRecordChildList } HistoryMutationRecord
 * @typedef { Object } PreviewableOperation
 * @property { Function } commit
 * @property { Function } preview
 * @property { Function } revert
 */

/**
 * @typedef { Object } HistoryShared
 * @property { HistoryPlugin['addCustomMutation'] } addCustomMutation
 * @property { HistoryPlugin['applyCustomMutation'] } applyCustomMutation
 * @property { HistoryPlugin['addExternalStep'] } addExternalStep
 * @property { HistoryPlugin['addStep'] } addStep
 * @property { HistoryPlugin['canRedo'] } canRedo
 * @property { HistoryPlugin['canUndo'] } canUndo
 * @property { HistoryPlugin['ignoreDOMMutations'] } ignoreDOMMutations
 * @property { HistoryPlugin['getHistorySteps'] } getHistorySteps
 * @property { HistoryPlugin['getNodeById'] } getNodeById
 * @property { HistoryPlugin['makePreviewableOperation'] } makePreviewableOperation
 * @property { HistoryPlugin['makePreviewableAsyncOperation'] } makePreviewableAsyncOperation
 * @property { HistoryPlugin['makeSavePoint'] } makeSavePoint
 * @property { HistoryPlugin['makeSnapshotStep'] } makeSnapshotStep
 * @property { HistoryPlugin['redo'] } redo
 * @property { HistoryPlugin['reset'] } reset
 * @property { HistoryPlugin['resetFromSteps'] } resetFromSteps
 * @property { HistoryPlugin['serializeSelection'] } serializeSelection
 * @property { HistoryPlugin['stageSelection'] } stageSelection
 * @property { HistoryPlugin['stageFocus'] } stageFocus
 * @property { HistoryPlugin['undo'] } undo
 * @property { HistoryPlugin['getIsPreviewing'] } getIsPreviewing
 * @property { HistoryPlugin['setStepExtra'] } setStepExtra
 * @property { HistoryPlugin['getIsCurrentStepModified'] } getIsCurrentStepModified
 */

/**
 * @typedef {((record: HistoryMutationRecord) => void)[]} attribute_change_handlers
 * @typedef {(() => void)[]} before_add_step_handlers
 * @typedef {((records: HistoryMutationRecord[]) => void)[]} before_filter_mutation_record_handlers
 * @typedef {((root: HTMLElement) => void)[]} content_updated_handlers
 * @typedef {(() => void)[]} external_step_added_handlers
 * @typedef {((records: HistoryMutationRecord[], currentOperation: "original"|"undo"|"redo"|"restore") => void)[]} handleNewRecords
 * @typedef {(() => void)[]} history_cleaned_handlers
 * @typedef {(() => void)[]} history_reset_handlers
 * @typedef {(() => void)[]} history_reset_from_steps_handlers
 * @typedef {((revertedStep: HistoryStep) => void)[]} post_redo_handlers
 * @typedef {((revertedStep: HistoryStep) => void)[]} post_undo_handlers
 * @typedef {(() => void)[]} restore_savepoint_handlers
 * @typedef {((arg: { step: HistoryStep, stepCommonAncestor: HTMLElement, isPreviewing: boolean }) => void)[]} step_added_handlers
 * @typedef {((record: HistoryMutationRecord) => boolean)[]} savable_mutation_record_predicates
 * @typedef {((step: HistoryStep) => boolean)[]} unreversible_step_predicates
 * @typedef {((
 * arg: {
 * target: Node,
 * attributeName: string,
 * oldValue: string,
 * value: string,
 * reverse: boolean,
 * },
 * options: { forNewStep: boolean }
 * ) => string)[]} attribute_change_processors
 * @typedef {((step: HistoryStep) => HistoryStep)[]} history_step_processors
 * @typedef {((node: Node, childTreesToSerialize: Tree[]) => Tree[])[]} serializable_descendants_processors
 * @typedef {((node: Node, attributeName: string, attributeValue: string) => boolean)[]} set_attribute_overrides
 */

const CONTENT_MUTATION_TYPES = new Set(["characterData", "remove", "add"]);

export class HistoryPlugin extends Plugin {
    static id = "history";
    static dependencies = ["selection", "sanitize"];
    static shared = [
        "addCustomMutation",
        "applyCustomMutation",
        "addExternalStep",
        "addStep",
        "canRedo",
        "canUndo",
        "ignoreDOMMutations",
        "getHistorySteps",
        "getNodeById",
        "makePreviewableOperation",
        "makePreviewableAsyncOperation",
        "makeSavePoint",
        "makeSnapshotStep",
        "redo",
        "reset",
        "resetFromSteps",
        "serializeSelection",
        "stageSelection",
        "stageFocus",
        "undo",
        "getIsPreviewing",
        "setStepExtra",
        "getIsCurrentStepModified",
    ];
    /** @type {import("plugins").EditorResources} */
    resources = {
        user_commands: [
            {
                id: "historyUndo",
                description: _t("Undo"),
                icon: "fa-undo",
                run: this.undo.bind(this),
            },
            {
                id: "historyRedo",
                description: _t("Redo"),
                icon: "fa-repeat",
                run: this.redo.bind(this),
            },
        ],
        ...(hasTouch() && {
            toolbar_groups: withSequence(5, { id: "historyMobile" }),
            toolbar_items: [
                {
                    id: "undo",
                    groupId: "historyMobile",
                    commandId: "historyUndo",
                    isDisabled: () => !this.canUndo(),
                    namespaces: ["compact", "expanded"],
                },
                {
                    id: "redo",
                    groupId: "historyMobile",
                    commandId: "historyRedo",
                    isDisabled: () => !this.canRedo(),
                    namespaces: ["compact", "expanded"],
                },
            ],
        }),
        shortcuts: [
            { hotkey: "control+z", commandId: "historyUndo", global: true },
            { hotkey: "control+y", commandId: "historyRedo", global: true },
            { hotkey: "control+shift+z", commandId: "historyRedo", global: true },
        ],
        start_edition_handlers: () => {
            this.enableObserver();
            this.reset(this.config.content);
        },
        on_prepare_drag_handlers: this.disableIsCurrentStepModifiedWarning.bind(this),
    };

    setup() {
        this.mutationFilteredClasses = new Set(this.getResource("system_classes"));
        this.mutationFilteredAttributes = new Set(
            this.getResource("system_attributes"),
        );
        this._onKeyupResetContenteditableNodes = [];
        this.addDomListener(
            this.document,
            "beforeinput",
            this._onDocumentBeforeInput.bind(this),
        );
        this.addDomListener(this.document, "input", this._onDocumentInput.bind(this));
        this.addGlobalDomListener("pointerup", (ev) => {
            if (this.editable.contains(ev.target)) {
                this.stageSelection();
            }
        });
        this.observer = new MutationObserver((records) =>
            this.handleNewRecords(records),
        );
        this.enableObserverCallbacks = new Set();
        this._cleanups.push(() => this.observer.disconnect());
        this.clean();
    }

    getIsPreviewing() {
        return this.isPreviewing;
    }

    clean() {
        this.handleObserverRecords();
        /** @type { HistoryStep[] } */
        this.steps = [];
        /** @type { HistoryStep } */
        this.currentStep = this.processHistoryStep({
            selection: {},
            mutations: [],
            id: this.generateId(),
            previousStepId: undefined,
            extraStepInfos: {},
        });
        /** @type {Set<string>} */
        this.revertedSteps = new Set();
        /** @type {Set<string>} */
        this.discardedSteps = new Set();
        this.nodeMap = new NodeMap();
        /** @type { WeakMap<Node, { attributes: Map<string, string>, classList: Map<string, boolean>, characterData: Map<string, string> }> } */
        this.lastObservedState = new WeakMap();
        this.setNodeId(this.editable);
        this.dispatchTo("history_cleaned_handlers");
    }
    /**
     * @param {string} id
     * @returns {Node}
     */
    getNodeById(id) {
        return this.nodeMap.getNode(id);
    }
    /**
     * @param { string } content
     */
    reset(content) {
        this.clean();
        this.stageSelection();
        this.steps.push(this.makeSnapshotStep());
        this.dispatchTo("history_reset_handlers", content);
    }
    /**
     * @param { HistoryStep[] } steps
     */
    resetFromSteps(steps) {
        this.withObserverOff(() => {
            this.editable.replaceChildren();
            this.clean();
            this.stageSelection();
            for (const step of steps) {
                this.applyMutations(step.mutations);
            }
            this.steps = steps;
        });
        this.dispatchTo("history_reset_from_steps_handlers");
    }
    makeSnapshotStep() {
        return {
            selection: {
                anchorNode: undefined,
                anchorOffset: undefined,
                focusNode: undefined,
                focusOffset: undefined,
            },
            mutations: childNodes(this.editable)
                .filter((node) => this.nodeMap.hasNode(node))
                .map((node) => ({
                    type: "add",
                    parentNodeId: "root",
                    nodeId: this.nodeMap.getId(node),
                    serializedNode: this.serializeNode(node),
                    nextNodeId: null,
                })),
            id: this.steps[this.steps.length - 1]?.id || this.generateId(),
            previousStepId: undefined,
        };
    }

    getHistorySteps() {
        return this.steps;
    }
    /**
     * @param { HistoryStep } step
     */
    processHistoryStep(step) {
        for (const fn of this.getResource("history_step_processors")) {
            step = fn(step);
        }
        return step;
    }

    enableObserver() {
        this.observer.observe(this.editable, {
            childList: true,
            subtree: true,
            attributes: true,
            attributeOldValue: true,
            characterData: true,
            characterDataOldValue: true,
        });
    }

    disableObserver() {
        const enableObserver = () => {
            this.enableObserverCallbacks.delete(enableObserver);
            if (this.enableObserverCallbacks.size > 0) {
                return;
            }
            this.handleObserverRecords();
            this.isObserverDisabled = false;
        };
        this.enableObserverCallbacks.add(enableObserver);
        this.handleObserverRecords();
        this.isObserverDisabled = true;
        return enableObserver;
    }

    /**
     * @param {Function} callback
     */
    ignoreDOMMutations(callback) {
        const enableObserver = this.disableObserver();
        try {
            return callback();
        } finally {
            enableObserver();
        }
    }

    withObserverOff(callback) {
        this.handleObserverRecords();
        this.observer.disconnect();
        try {
            return callback();
        } finally {
            this.enableObserver();
        }
    }

    handleObserverRecords(dispatch = true) {
        this.handleNewRecords(this.observer.takeRecords(), dispatch);
    }

    /**
     * @param { MutationRecord[] } mutationRecords
     * @returns { HistoryMutationRecord[] }
     */
    processNewRecords(mutationRecords) {
        if (this.observer.takeRecords().length) {
            throw new Error("MutationObserver has pending records");
        }
        mutationRecords = this.filterMutationRecords(mutationRecords);
        /** @type {HistoryMutationRecord[]} */
        let records = this.transformToHistoryMutationRecords(mutationRecords);
        records = records.filter((record) => !this.isSystemMutationRecord(record));
        records = this.filterAndAdjustHistoryMutationRecords(records);
        this.stageRecords(records);
        records
            .filter(({ type }) => type === "attributes")
            .forEach((record) => this.dispatchTo("attribute_change_handlers", record));
        return records;
    }

    /**
     * @param {HistoryMutationRecord} record
     */
    isValidRecord(record) {
        switch (record.type) {
            case "attributes":
            case "classList":
            case "characterData":
                return record.value !== record.oldValue;
            case "childList":
                return (
                    (record.addedTrees.length || record.removedTrees.length) &&
                    (record.previousSibling !== undefined ||
                        record.nextSibling !== undefined)
                );
        }
    }

    dispatchContentUpdated() {
        if (!this.currentStep?.mutations?.length) {
            return;
        }
        const root = this.getMutationsRoot(this.currentStep.mutations);
        if (!root) {
            return;
        }
        this.dispatchTo("content_updated_handlers", root);
    }

    /**
     * @param { MutationRecord[] } records
     * @param { boolean } [dispatch]
     */
    handleNewRecords(records, dispatch = true) {
        const processedRecords = this.processNewRecords(records);
        if (processedRecords.length) {
            if (dispatch) {
                const stepType = this.currentStep.type;
                this.dispatchTo("handleNewRecords", processedRecords, stepType);
            }
            this.processNewRecords(this.observer.takeRecords());
            this.dispatchContentUpdated();
        }
    }

    /**
     * @param {HistoryMutationRecord} record
     */
    setIdOnAddedNodes(record) {
        if (record.type !== "childList") {
            return;
        }
        record.addedTrees
            .flatMap(treeToNodes)
            .filter((node) => !this.nodeMap.hasNode(node))
            .forEach((node) => this.nodeMap.set(this.generateId(), node));
    }

    /**
     * @param { MutationRecord[] } records
     * @returns { MutationRecord[] }
     */
    filterMutationRecords(records) {
        records = this.filterAttributeMutationRecords(records);
        records = this.filterSameTextContentMutationRecords(records);
        records = this.filterOutIntermediateStateMutationRecords(records);
        return records;
    }

    /**
     * @param { MutationRecord[] } records
     */
    filterAttributeMutationRecords(records) {
        return records.filter((record) => {
            if (record.type !== "attributes") {
                return true;
            }
            if (record.target === this.editable) {
                return false;
            }
            if (record.attributeName === "contenteditable") {
                return false;
            }
            return true;
        });
    }

    /**
     * @param { MutationRecord[] } records
     * @returns { MutationRecord[] }
     */
    filterSameTextContentMutationRecords(records) {
        const filteredRecords = [];
        for (const record of records) {
            if (record.type === "childList" && this.isSameTextContentMutation(record)) {
                const { addedNodes, removedNodes } = record;
                const oldId = this.nodeMap.getId(removedNodes[0]);
                if (oldId) {
                    this.nodeMap.set(oldId, addedNodes[0]);
                    continue;
                }
            }
            filteredRecords.push(record);
        }
        return filteredRecords;
    }

    /**
     * @param { MutationRecord[] } records
     */
    filterOutIntermediateStateMutationRecords(records) {
        const isFirstAttributeOccurrence = trackOccurrencesPair();
        const isFirstCharDataOccurence = trackOccurrences();
        const filteredRecords = [];
        for (const record of records) {
            if (record.type === "attributes") {
                if (isFirstAttributeOccurrence(record.target, record.attributeName)) {
                    filteredRecords.push(record);
                }
            } else if (record.type === "characterData") {
                if (isFirstCharDataOccurence(record.target)) {
                    filteredRecords.push(record);
                }
            } else {
                filteredRecords.push(record);
            }
        }
        return filteredRecords;
    }

    /**
     * @param {MutationRecord[]} records
     * @returns {HistoryMutationRecord[]}
     */
    transformToHistoryMutationRecords(records) {
        records = this.transformChildListRecords(records);
        return records.flatMap((record) => {
            if (record.type === "attributes") {
                if (record.attributeName === "class") {
                    return this.splitClassMutationRecord(record);
                }
                const oldValue = record.oldValue === undefined ? null : record.oldValue;
                const value = record.target.getAttribute(record.attributeName);
                return {
                    ...pick(record, "type", "target", "attributeName"),
                    oldValue,
                    value,
                };
            }
            if (record.type === "characterData") {
                const value = record.target.textContent;
                return { ...pick(record, "type", "target", "oldValue"), value };
            }
            return record;
        });
    }

    /**
     * @param {MutationRecord[]} records
     * @returns {(HistoryMutationRecord|MutationRecord)[]}
     */
    transformChildListRecords(records) {
        /** @type {WeakMap<Node, Node[]>} */
        const childListSnapshot = new WeakMap();
        /** @type {(node: Node) => Node[]} */
        const getChildListSnapshot = (node) =>
            childListSnapshot.get(node) || childNodes(node);
        /** @type {(node: Node) => Tree} */
        const makeSnapshotTree = (node) => ({
            node,
            children: getChildListSnapshot(node).map(makeSnapshotTree),
        });

        /** @type {(childListAfter: Node[], record: MutationRecord) => Node[]} */
        const reconstructChildList = (childListAfter, record) => {
            const { removedNodes, previousSibling, nextSibling } = record;
            const previousSiblingNodes = previousSibling
                ? childListAfter.slice(0, childListAfter.indexOf(previousSibling) + 1)
                : [];
            const nextSiblingNodes = nextSibling
                ? childListAfter.slice(childListAfter.indexOf(nextSibling))
                : [];
            return [...previousSiblingNodes, ...removedNodes, ...nextSiblingNodes];
        };

        return records
            .toReversed()
            .map((/** @type {MutationRecord} */ record) => {
                if (record.type !== "childList") {
                    return record;
                }
                const transformedRecord = {
                    ...pick(record, "type", "previousSibling", "nextSibling", "target"),
                    addedTrees: [...record.addedNodes].map(makeSnapshotTree),
                    removedTrees: [...record.removedNodes].map(makeSnapshotTree),
                };
                const childListAfterMutation = getChildListSnapshot(record.target);
                const childListBefore = reconstructChildList(
                    childListAfterMutation,
                    record,
                );
                childListSnapshot.set(record.target, childListBefore);
                return transformedRecord;
            })
            .toReversed();
    }

    /**
     * @param { MutationRecord } record
     * @returns { MutationRecordClassList[]}
     */
    splitClassMutationRecord(record) {
        const oldValue = record.oldValue?.split(" ").filter(Boolean);
        const classesBefore = new Set(oldValue);
        const classesAfter = new Set(record.target.classList);
        const setDifference = (setA, setB) => {
            const diff = new Set(setA);
            setB.forEach((item) => diff.delete(item));
            return diff;
        };
        const addedClasses = setDifference(classesAfter, classesBefore);
        const removedClasses = setDifference(classesBefore, classesAfter);

        /** @type {(className: string, isAdded: boolean) => MutationRecordClassList } */
        const createClassRecord = (className, isAdded) => ({
            type: "classList",
            target: record.target,
            className,
            value: isAdded,
            oldValue: !isAdded,
        });
        return [
            ...[...addedClasses].map((cls) => createClassRecord(cls, true)),
            ...[...removedClasses].map((cls) => createClassRecord(cls, false)),
        ];
    }

    /**
     * @param { HistoryMutationRecord } record
     */
    isSystemMutationRecord(record) {
        if (record.type === "attributes") {
            return this.mutationFilteredAttributes.has(record.attributeName);
        }
        if (record.type === "classList") {
            return this.mutationFilteredClasses.has(record.className);
        }
        return false;
    }

    /**
     * @param {HistoryMutationRecord[]} records
     * @returns {HistoryMutationRecord[]}
     */
    filterAndAdjustHistoryMutationRecords(records) {
        this.dispatchTo("before_filter_mutation_record_handlers", records);
        const savableRecordPredicates = this.getResource(
            "savable_mutation_record_predicates",
        );
        const isRecordSavable = (record) =>
            savableRecordPredicates.every((p) => p(record));
        const result = [];
        for (const record of records) {
            if (!this.isObservedNode(record.target)) {
                continue;
            }
            if (this.isObserverDisabled || !isRecordSavable(record)) {
                if (record.type !== "childList") {
                    this.storeOldValue(record);
                }
                continue;
            }
            const updatedRecord =
                record.type === "childList"
                    ? this.updateChildListRecord(record)
                    : this.updateOldValue(record);
            if (this.isValidRecord(updatedRecord)) {
                this.setIdOnAddedNodes(record);
                result.push(updatedRecord);
            }
        }
        return result;
    }

    /**
     * @param {Node} node
     * @returns {boolean}
     */
    isObservedNode(node) {
        return this.nodeMap.hasNode(node);
    }

    /**
     * @param {MutationRecordAttributes|MutationRecordClassList|MutationRecordCharacterData} record
     */
    storeOldValue(record) {
        const { stateMap, key } = this.getObservedStateStorage(record);
        if (!stateMap.has(key)) {
            stateMap.set(key, record.oldValue);
        }
    }

    /**
     * @param {MutationRecordAttributes|MutationRecordClassList|MutationRecordCharacterData} record
     * @returns {MutationRecordAttributes|MutationRecordClassList|MutationRecordCharacterData}
     */
    updateOldValue(record) {
        const { stateMap, key } = this.getObservedStateStorage(record);
        if (!stateMap.has(key)) {
            return record;
        }
        const lastObservedValue = stateMap.get(key);
        stateMap.delete(key);
        return { ...record, oldValue: lastObservedValue };
    }

    /**
     * @param {HistoryMutationRecord} record
     * @returns { { stateMap: Map, key: string } }
     */
    getObservedStateStorage(record) {
        if (!this.lastObservedState.has(record.target)) {
            this.lastObservedState.set(record.target, {
                attributes: new Map(),
                classList: new Map(),
                characterData: new Map(),
            });
        }
        const stateMap = this.lastObservedState.get(record.target)[record.type];
        switch (record.type) {
            case "attributes":
                return { stateMap, key: record.attributeName };
            case "classList":
                return { stateMap, key: record.className };
            case "characterData":
                return { stateMap, key: "textContent" };
            default:
                throw new Error(`Unsupported mutation type: ${record.type}`);
        }
    }

    /**
     * @param {MutationRecordChildList} record
     * @returns {MutationRecordChildList}
     */
    updateChildListRecord(record) {
        const isValidReference = (node) => node === null || this.isObservedNode(node);
        const updateSibling = (sibling) =>
            isValidReference(sibling) ? sibling : undefined;
        const previousSibling = updateSibling(record.previousSibling);
        const nextSibling = updateSibling(record.nextSibling);

        const removeUnobservedNodes = (tree) => {
            if (!this.isObservedNode(tree.node)) {
                return null;
            }
            return {
                node: tree.node,
                children: tree.children.map(removeUnobservedNodes).filter(Boolean),
            };
        };
        const removedTrees = record.removedTrees
            .map(removeUnobservedNodes)
            .filter(Boolean);

        return {
            ...record,
            previousSibling,
            nextSibling,
            removedTrees,
        };
    }

    /**
     * @param { MutationRecord } record
     */
    isSameTextContentMutation(record) {
        const { addedNodes, removedNodes } = record;
        return (
            record.type === "childList" &&
            addedNodes.length === 1 &&
            removedNodes.length === 1 &&
            addedNodes[0].nodeType === Node.TEXT_NODE &&
            removedNodes[0].nodeType === Node.TEXT_NODE &&
            addedNodes[0].textContent === removedNodes[0].textContent
        );
    }

    stageSelection() {
        this.stageFocus();
        const selection = this.dependencies.selection.getEditableSelection();
        if (this.getIsCurrentStepModified()) {
            console.warn(
                `should not have any "characterData", "remove" or "add" mutations in current step when you update the selection`,
            );
            return;
        }
        this.currentStep.selection = this.serializeSelection(selection);
    }
    stageFocus() {
        let activeElement = this.document.activeElement;
        if (!activeElement) {
            return;
        }
        if (activeElement.contains(this.editable)) {
            activeElement = this.editable;
        }
        if (this.editable.contains(activeElement)) {
            this.currentStep.activeElementId = this.setNodeId(activeElement);
        }
    }
    /**
     * @param { HistoryMutationRecord[] } records
     */
    stageRecords(records) {
        for (const record of records) {
            switch (record.type) {
                case "characterData":
                case "classList":
                case "attributes": {
                    const nodeId = this.nodeMap.getId(record.target);
                    this.currentStep.mutations.push({
                        ...omit(record, "target"),
                        nodeId,
                    });
                    break;
                }
                case "childList": {
                    this.currentStep.mutations.push(
                        ...this.splitChildListRecord(record),
                    );
                    break;
                }
            }
        }
    }

    /**
     * @param {MutationRecordChildList} record
     * @returns { (HistoryMutationRemove|HistoryMutationAdd)[] }
     */
    splitChildListRecord(record) {
        const parentNodeId = this.nodeMap.getId(record.target);
        if (!parentNodeId) {
            throw new Error("Unknown parent node");
        }

        const makeSingleNodeRecords = (trees, type) =>
            trees.map((tree, index, treeList) => {
                const node = tree.node;
                const nodeList = treeList.map((t) => t.node);
                const [previousSibling, nextSibling] =
                    type === "add"
                        ? [
                              nodeList[index - 1] || record.previousSibling,
                              record.nextSibling,
                          ]
                        : [
                              record.previousSibling,
                              nodeList[index + 1] || record.nextSibling,
                          ];
                const [nextNodeId, previousNodeId] = [nextSibling, previousSibling].map(
                    (sibling) =>
                        sibling ? this.nodeMap.getId(sibling) : sibling,
                );
                const nodeId = this.nodeMap.getId(node);
                const serializedNode = this.serializeTree(tree);
                return {
                    type,
                    nodeId,
                    parentNodeId,
                    serializedNode,
                    nextNodeId,
                    previousNodeId,
                };
            });

        return [
            ...makeSingleNodeRecords(record.removedTrees, "remove"),
            ...makeSingleNodeRecords(record.addedTrees, "add"),
        ];
    }

    applyCustomMutation({ apply, revert }) {
        apply();
        this.addCustomMutation({ apply, revert });
    }

    addCustomMutation({ apply, revert }) {
        const customMutation = {
            type: "custom",
            apply: () => {
                apply();
                this.addCustomMutation({ apply, revert });
            },
            revert: () => {
                revert();
                this.addCustomMutation({ apply: revert, revert: apply });
            },
        };
        this.currentStep.mutations.push(customMutation);
    }

    /**
     * @param { Node } node
     */
    setNodeId(node) {
        let id = this.nodeMap.getId(node);
        if (!id) {
            id = node === this.editable ? "root" : this.generateId();
            this.nodeMap.set(id, node);
            node = node.firstChild;
            while (node) {
                this.setNodeId(node);
                node = node.nextSibling;
            }
        }
        return id;
    }
    generateId() {
        return generateId();
    }

    /**
     * @param { Object } [params]
     * @param { "original"|"undo"|"redo"|"restore" } [params.type]
     * @param {Object} [params.extraStepInfos]
     */
    addStep({ type = "original", extraStepInfos } = {}) {

        const currentStep = this.currentStep;
        currentStep.type = type;
        this.handleObserverRecords();
        const currentMutationsCount = currentStep.mutations.length;
        if (currentMutationsCount === 0) {
            return false;
        }
        const stepCommonAncestor =
            this.getMutationsRoot(currentStep.mutations) || this.editable;
        this.dispatchTo("normalize_handlers", stepCommonAncestor, type);
        this.handleObserverRecords(false);
        if (currentMutationsCount === currentStep.mutations.length) {
            this.dispatchContentUpdated();
        }

        currentStep.previousStepId = this.steps.at(-1)?.id;

        currentStep.selectionAfter = this.serializeSelection(
            this.dependencies.selection.getEditableSelection(),
        );
        this.steps.push(currentStep);
        this.dispatchTo("before_add_step_handlers");
        if (extraStepInfos) {
            currentStep.extraStepInfos = extraStepInfos;
        }
        this.currentStep = this.processHistoryStep({
            id: this.generateId(),
            type: undefined,
            selection: {},
            mutations: [],
            previousStepId: undefined,
            extraStepInfos: {},
        });
        this.stageSelection();
        this.dispatchTo("step_added_handlers", {
            step: currentStep,
            stepCommonAncestor,
            isPreviewing: this.isPreviewing,
        });
        this.config.onChange?.({ isPreviewing: this.isPreviewing });
        return currentStep;
    }
    canUndo() {
        return this.getNextUndoIndex() > 0;
    }
    canRedo() {
        return this.getNextRedoIndex() > 0;
    }
    undo() {
        if (this.steps.length === 1) {
            return;
        }
        this.handleObserverRecords();
        const lastStep = this.currentStep;
        this.revertMutations(lastStep.mutations);
        this.observer.takeRecords();
        lastStep.mutations = [];

        const pos = this.getNextUndoIndex();
        let revertedStep;
        if (pos > 0) {
            revertedStep = this.steps[pos];
            this.revertedSteps.add(revertedStep.id);
            this.revertMutations(revertedStep.mutations, { forNewStep: true });
            this.setSerializedFocus(revertedStep.activeElementId);
            this.stageFocus();
            this.setSerializedSelection(revertedStep.selection);
            this.currentStep.selection = revertedStep.selectionAfter;
            this.addStep({ type: "undo", extraStepInfos: revertedStep.extraStepInfos });
        }
        this.dispatchTo("post_undo_handlers", revertedStep);
    }
    redo() {
        this.handleObserverRecords();
        this.revertMutations(this.currentStep.mutations);
        this.observer.takeRecords();
        this.currentStep.mutations = [];

        const pos = this.getNextRedoIndex();
        let revertedStep;
        if (pos > 0) {
            revertedStep = this.steps[pos];
            this.revertedSteps.add(revertedStep.id);
            this.revertMutations(revertedStep.mutations, { forNewStep: true });
            this.setSerializedFocus(revertedStep.activeElementId);
            this.stageFocus();
            this.setSerializedSelection(revertedStep.selection);
            this.currentStep.selection = revertedStep.selectionAfter;
            this.addStep({ type: "redo", extraStepInfos: revertedStep.extraStepInfos });
        }
        this.dispatchTo("post_redo_handlers", revertedStep);
    }
    /**
     * @param { SerializedSelection } selection
     */
    setSerializedSelection(selection) {
        if (!selection.anchorNodeId) {
            return;
        }
        const anchorNode = this.nodeMap.getNode(selection.anchorNodeId);
        if (!anchorNode) {
            return;
        }
        const newSelection = {
            anchorNode,
            anchorOffset: selection.anchorOffset,
        };
        const focusNode = this.nodeMap.getNode(selection.focusNodeId);
        if (focusNode) {
            newSelection.focusNode = focusNode;
            newSelection.focusOffset = selection.focusOffset;
        }
        this.dependencies.selection.setSelection(newSelection, { normalize: false });
    }
    /**
     * @param { string } activeElementId
     */
    setSerializedFocus(activeElementId) {
        const elementToFocus =
            activeElementId === "root"
                ? this.editable
                : activeElementId && this.nodeMap.getNode(activeElementId);
        if (
            elementToFocus?.isConnected &&
            elementToFocus !== this.document.activeElement
        ) {
            elementToFocus.focus();
        }
    }
    getNextUndoIndex() {
        for (let index = this.steps.length - 1; index >= 0; index--) {
            const step = this.steps[index];
            if (!this.isReversibleStep(index) || this.discardedSteps.has(step.id)) {
                continue;
            }
            if (
                ["original", "redo"].includes(step.type) &&
                !this.revertedSteps.has(step.id)
            ) {
                return index;
            }
        }
        return -1;
    }
    /**
     * @param { number } index
     */
    isReversibleStep(index) {
        const step = this.steps[index];
        if (!step) {
            return false;
        }
        return !this.getResource("unreversible_step_predicates").some((predicate) =>
            predicate(step),
        );
    }
    getNextRedoIndex() {
        for (let index = this.steps.length - 1; index >= 0; index--) {
            const step = this.steps[index];
            if (!this.isReversibleStep(index) || this.discardedSteps.has(step.id)) {
                continue;
            }
            if (step.type === "original") {
                return -1;
            }
            if (step.type === "undo" && !this.revertedSteps.has(step.id)) {
                return index;
            }
        }
        return -1;
    }
    /**
     * @param { HistoryStep } newStep
     * @param { number } index
     */
    addExternalStep(newStep, index) {
        this.withObserverOff(() => {
            this.revertMutations(this.currentStep.mutations);

            const stepsAfterNewStep = this.steps.slice(index);

            for (const stepToRevert of stepsAfterNewStep.slice().reverse()) {
                this.revertMutations(stepToRevert.mutations);
            }
            this.applyMutations(newStep.mutations);
            this.dispatchTo(
                "normalize_handlers",
                this.getMutationsRoot(newStep.mutations) || this.editable,
            );
            this.steps.splice(index, 0, newStep);
            for (const stepToApply of stepsAfterNewStep) {
                this.applyMutations(stepToApply.mutations);
            }
            this.applyMutations(this.currentStep.mutations);
            this.dispatchTo("external_step_added_handlers");
        });
    }
    /**
     * @param { HistoryMutation[] } mutations
     * @param { Object } options
     * @param { boolean } options.forNewStep
     * @param { boolean } options.reverse
     */
    applyMutations(mutations, { forNewStep = false, reverse } = {}) {
        if (forNewStep) {
            this.fixClassListMutationsForNewStep(mutations);
        }
        for (const mutation of mutations) {
            switch (mutation.type) {
                case "custom": {
                    mutation.apply();
                    break;
                }
                case "characterData": {
                    const node = this.nodeMap.getNode(mutation.nodeId);
                    if (node) {
                        node.textContent = mutation.value;
                    }
                    break;
                }
                case "classList": {
                    const node = this.nodeMap.getNode(mutation.nodeId);
                    if (node) {
                        toggleClass(node, mutation.className, mutation.value);
                    }
                    break;
                }
                case "attributes": {
                    const node = this.nodeMap.getNode(mutation.nodeId);
                    if (node) {
                        let value = mutation.value;
                        for (const cb of this.getResource(
                            "attribute_change_processors",
                        )) {
                            value = cb(
                                {
                                    target: node,
                                    attributeName: mutation.attributeName,
                                    oldValue: mutation.oldValue,
                                    value,
                                    reverse,
                                },
                                { forNewStep },
                            );
                        }
                        this.setAttribute(node, mutation.attributeName, value);
                    }
                    break;
                }
                case "remove": {
                    this.applyRemoveMutation(mutation);
                    break;
                }
                case "add": {
                    this.applyAddMutation(mutation);
                    break;
                }
            }
        }
    }

    /**
     * @param { HistoryMutation[] } mutations
     */
    fixClassListMutationsForNewStep(mutations) {
        const isFirstOcurrence = trackOccurrencesPair();
        const nonObservableClassMutations = mutations
            .filter((mutation) => mutation.type === "classList")
            .filter(({ nodeId, className }) => isFirstOcurrence(nodeId, className))
            .map((mutation) => ({
                ...mutation,
                node: this.nodeMap.getNode(mutation.nodeId),
            }))
            .filter(
                ({ node, className, value }) =>
                    value === node?.classList.contains(className),
            );
        if (nonObservableClassMutations.length) {
            const setToOldValue = ({ node, className, oldValue }) =>
                toggleClass(node, className, oldValue);
            this.withObserverOff(() =>
                nonObservableClassMutations.forEach(setToOldValue),
            );
        }
    }

    /**
     * @param {HistoryMutationRemove} mutation
     */
    applyRemoveMutation(mutation) {
        const parent = this.nodeMap.getNode(mutation.parentNodeId);
        const toRemove = this.nodeMap.getNode(mutation.nodeId);
        if (!toRemove) {
            console.warn(
                "Mutation could not be applied, node to remove is unknown.",
                mutation,
            );
            return;
        }
        if (toRemove.parentElement !== parent) {
            console.warn(
                "Mutation could not be applied, parent node does not match.",
                mutation,
            );
            return;
        }
        toRemove.remove();
    }

    /**
     * @param {HistoryMutationAdd} mutation
     */
    applyAddMutation(mutation) {
        const { nodeId, serializedNode, parentNodeId, nextNodeId, previousNodeId } =
            mutation;

        const toAdd =
            this.nodeMap.getNode(nodeId) || this.unserializeNode(serializedNode);
        if (!toAdd) {
            return;
        }

        const parent = this.nodeMap.getNode(parentNodeId);
        if (!parent) {
            console.warn(
                "Mutation could not be applied, parent node is missing.",
                mutation,
            );
            return;
        }
        if (previousNodeId === null) {
            parent.prepend(toAdd);
            return;
        }
        if (nextNodeId === null) {
            parent.append(toAdd);
            return;
        }
        const isValid = (node) => node?.parentNode === parent;
        const previousNode = this.nodeMap.getNode(previousNodeId);
        if (isValid(previousNode)) {
            previousNode.after(toAdd);
            return;
        }
        const nextNode = this.nodeMap.getNode(nextNodeId);
        if (isValid(nextNode)) {
            nextNode.before(toAdd);
            return;
        }
        console.warn(
            "Mutation could not be applied, reference nodes are invalid.",
            mutation,
        );
    }

    revertMutations(mutations, { forNewStep = false } = {}) {
        const revertedMutations = mutations.map((mutation) => {
            switch (mutation.type) {
                case "characterData":
                case "classList":
                case "attributes":
                    return {
                        ...mutation,
                        value: mutation.oldValue,
                        oldValue: mutation.value,
                    };
                case "remove":
                    return { ...mutation, type: "add" };
                case "add":
                    return { ...mutation, type: "remove" };
                case "custom":
                    return {
                        ...mutation,
                        apply: mutation.revert,
                        revert: mutation.apply,
                    };
                default:
                    throw new Error(`Unknown mutation type: ${mutation.type}`);
            }
        });
        this.applyMutations(revertedMutations.toReversed(), {
            forNewStep,
            reverse: true,
        });
    }

    /**
     * @param { EditorSelection } selection
     * @returns { SerializedSelection }
     */
    serializeSelection(selection) {
        return {
            anchorNodeId: this.nodeMap.getId(selection.anchorNode),
            anchorOffset: selection.anchorOffset,
            focusNodeId: this.nodeMap.getId(selection.focusNode),
            focusOffset: selection.focusOffset,
        };
    }
    /**
     * @param {HistoryMutation[]} mutations
     * @returns {HTMLElement|null}
     */
    getMutationsRoot(mutations) {
        const nodes = mutations
            .map((m) => this.nodeMap.getNode(m.parentNodeId || m.nodeId))
            .filter((node) => this.editable.contains(node));
        let commonAncestor = getCommonAncestor(nodes, this.editable);
        if (commonAncestor?.nodeType === Node.TEXT_NODE) {
            commonAncestor = commonAncestor.parentElement;
        }
        return commonAncestor;
    }
    /**
     * @returns {Function}
     */
    makeSavePoint() {
        this.handleObserverRecords();
        const draftMutations = this.currentStep.mutations.slice();
        const step = this.steps.at(-1);
        let applied = false;
        const selectionToRestore = this.dependencies.selection.preserveSelection();
        const extraToRestore = { ...this.currentStep.extraStepInfos };
        return () => {
            if (applied) {
                return;
            }
            applied = true;
            const stepIndex = this.steps.findLastIndex((item) => item === step);
            const lastRevertedStep = this.restoreToStep(stepIndex);
            if (lastRevertedStep?.selection && !draftMutations.length) {
                selectionToRestore.setCursor((cursor) => {
                    const anchorNode = this.nodeMap.getNode(
                        lastRevertedStep.selection.anchorNodeId,
                    );
                    const focusNode = this.nodeMap.getNode(
                        lastRevertedStep.selection.focusNodeId,
                    );
                    cursor.anchor.node = anchorNode;
                    cursor.anchor.offset = lastRevertedStep.selection.anchorOffset;

                    cursor.focus.node = focusNode;
                    cursor.focus.offset = lastRevertedStep.selection.focusOffset;
                });
            }
            this.applyMutations(draftMutations, { forNewStep: true });
            this.handleObserverRecords();
            selectionToRestore.restore();
            this.currentStep.extraStepInfos = extraToRestore;
            this.dispatchTo("restore_savepoint_handlers");
        };
    }
    /**
     * @param {Function} operation
     * @returns {PreviewableOperation}
     */
    makePreviewableOperation(operation) {
        let revertOperation = () => {};

        return {
            preview: (...args) => {
                revertOperation();
                revertOperation = this.makeSavePoint();
                this.isPreviewing = true;
                this.stageSelection();
                operation(...args);
                this.addStep();
            },
            commit: (...args) => {
                revertOperation();
                this.isPreviewing = false;
                operation(...args);
                this.addStep();
            },
            revert: () => {
                revertOperation();
                revertOperation = () => {};
                this.isPreviewing = false;
            },
        };
    }

    /**
     * @param {Function} operation
     * @returns {PreviewableOperation}
     */
    makePreviewableAsyncOperation(operation) {
        let revertOperation = () => {};

        return {
            preview: async (...args) => {
                await revertOperation();
                const def = new Deferred();
                const revertSavePoint = this.makeSavePoint();
                revertOperation = async () => {
                    await def;
                    revertSavePoint();
                };
                this.isPreviewing = true;
                try {
                    await operation(...args);
                } catch (error) {
                    revertSavePoint();
                    throw error;
                } finally {
                    def.resolve();
                }
                if (this.isDestroyed) {
                    return;
                }
                this.addStep();
            },
            commit: async (...args) => {
                await revertOperation();
                this.isPreviewing = false;
                const revertSavePoint = this.makeSavePoint();
                try {
                    await operation(...args);
                } catch (error) {
                    revertSavePoint();
                    throw error;
                }
                if (this.isDestroyed) {
                    return;
                }
                this.addStep();
            },
            revert: async () => {
                await revertOperation();
                revertOperation = () => {};
                this.isPreviewing = false;
            },
        };
    }

    /**
     * @param {Number} stepIndex
     * @returns {HistoryStep}
     */
    restoreToStep(stepIndex) {
        this.handleObserverRecords();
        this.revertMutations(this.currentStep.mutations);
        this.observer.takeRecords();
        this.currentStep.mutations = [];
        let lastRevertedStep = this.currentStep;

        if (stepIndex === this.steps.length - 1) {
            return;
        }
        for (let i = this.steps.length - 1; i > stepIndex; i--) {
            const currentStep = this.steps[i];
            this.revertMutations(currentStep.mutations, { forNewStep: true });
            this.processNewRecords(this.observer.takeRecords());
            if (this.isReversibleStep(i)) {
                this.discardedSteps.add(currentStep.id);
                lastRevertedStep = currentStep;
            }
        }
        for (let i = stepIndex + 1; i < this.steps.length; i++) {
            const currentStep = this.steps[i];
            if (!this.isReversibleStep(i)) {
                this.applyMutations(currentStep.mutations, { forNewStep: true });
                this.processNewRecords(this.observer.takeRecords());
            }
        }
        this.setSerializedSelection(lastRevertedStep.selection);
        this.dispatchContentUpdated();
        this.addStep({ type: "restore" });
        return lastRevertedStep;
    }

    setStepExtra(key, value) {
        this.currentStep.extraStepInfos[key] = value;
    }

    disableIsCurrentStepModifiedWarning() {
        this.ignoreIsCurrentStepModified = true;
        return () => {
            this.ignoreIsCurrentStepModified = false;
        };
    }

    getIsCurrentStepModified() {
        if (this.ignoreIsCurrentStepModified) {
            return false;
        }
        return this.currentStep.mutations.some((mutation) =>
            CONTENT_MUTATION_TYPES.has(mutation.type),
        );
    }

    /**
     * @param { Node } node
     * @param { string } attributeName
     * @param { string } attributeValue
     */
    setAttribute(node, attributeName, attributeValue) {
        if (
            this.delegateTo(
                "set_attribute_overrides",
                node,
                attributeName,
                attributeValue,
            )
        ) {
            return;
        }

        if (attributeValue !== null) {
            node.setAttribute(attributeName, attributeValue);
        } else {
            node.removeAttribute(attributeName);
        }
    }
    /**
     * @param { Node } node
     */
    serializeNode(node) {
        return this.serializeTree(nodeToTree(node));
    }
    /**
     * @param { SerializedNode } node
     * @returns { Node }
     */
    unserializeNode(node) {
        let [unserializedNode, newNodesMap] = this._unserializeNode(node, this.nodeMap);
        if (!unserializedNode) {
            return null;
        }
        const fakeNode = this.document.createElement("fake-el");
        fakeNode.appendChild(unserializedNode);
        this.dependencies.sanitize.sanitize(fakeNode, { IN_PLACE: true });
        unserializedNode = fakeNode.firstChild;
        if (!unserializedNode) {
            return null;
        }
        for (const node of [unserializedNode, ...descendants(unserializedNode)]) {
            if (this.nodeMap.hasNode(node)) {
                continue;
            }
            const id = newNodesMap.get(node);
            if (id) {
                this.nodeMap.set(id, node);
            }
        }
        return unserializedNode;
    }

    /**
     * @param {Tree} tree
     * @returns {SerializedNode|null}
     */
    serializeTree(tree) {
        const node = tree.node;
        const nodeId = this.nodeMap.getId(node);
        if (!nodeId) {
            return null;
        }
        const result = {
            nodeType: node.nodeType,
            nodeId: nodeId,
        };
        if (node.nodeType === Node.TEXT_NODE) {
            result.textValue = node.nodeValue;
        } else if (node.nodeType === Node.ELEMENT_NODE) {
            let childTreesToSerialize = tree.children;
            for (const cb of this.getResource("serializable_descendants_processors")) {
                childTreesToSerialize = cb(node, childTreesToSerialize);
            }
            result.tagName = node.tagName;
            result.attributes = Object.fromEntries(
                [...node.attributes].map((attr) => [attr.name, attr.value]),
            );
            result.children = childTreesToSerialize
                .map((tree) => this.serializeTree(tree))
                .filter(Boolean);
        }
        return result;
    }
    /**
     * @param { SerializedNode } serializedNode
     * @param { NodeMap} nodeMap
     * @param { Map<Node, string> } _map
     * @returns { [Node, Map<Node, string>] }
     */
    _unserializeNode(serializedNode, nodeMap = new NodeMap(), _map = new Map()) {
        let node = nodeMap.getNode(serializedNode.nodeId);
        if (node) {
            return [node, _map];
        }
        if (serializedNode.nodeType === Node.TEXT_NODE) {
            node = this.document.createTextNode(serializedNode.textValue);
        } else if (serializedNode.nodeType === Node.ELEMENT_NODE) {
            node = this.document.createElement(serializedNode.tagName);
            for (const key in serializedNode.attributes) {
                node.setAttribute(key, serializedNode.attributes[key]);
            }
            node.append(
                ...serializedNode.children
                    .map((child) => this._unserializeNode(child, nodeMap, _map)[0])
                    .filter(Boolean),
            );
        } else {
            console.warn("unknown node type");
            return [null, _map];
        }
        _map.set(node, serializedNode.nodeId);
        return [node, _map];
    }

    _onDocumentBeforeInput(ev) {
        if (this.editable.contains(ev.target)) {
            return;
        }
        if (["historyUndo", "historyRedo"].includes(ev.inputType)) {
            this._onKeyupResetContenteditableNodes.push(
                ...this.editable.querySelectorAll("[contenteditable=true]"),
            );
            if (this.editable.getAttribute("contenteditable") === "true") {
                this._onKeyupResetContenteditableNodes.push(this.editable);
            }

            for (const node of this._onKeyupResetContenteditableNodes) {
                node.setAttribute("contenteditable", false);
            }
        }
    }

    _onDocumentInput(ev) {
        if (
            ["historyUndo", "historyRedo"].includes(ev.inputType) &&
            this._onKeyupResetContenteditableNodes.length
        ) {
            for (const node of this._onKeyupResetContenteditableNodes) {
                node.setAttribute("contenteditable", true);
            }
            this._onKeyupResetContenteditableNodes = [];
        }
    }
}

/**
 * @param {Node} node
 * @returns {Tree}
 */
export function nodeToTree(node) {
    return {
        node,
        children: childNodes(node).map(nodeToTree),
    };
}

/**
 * @param {Tree} tree
 * @returns {Node[]}
 */
function treeToNodes(tree) {
    return [tree.node, ...tree.children.flatMap(treeToNodes)];
}

class NodeMap {
    constructor() {
        /** @type {Map<string, Node>} */
        const idToNodeMap = new Map();
        /** @type {Map<Node, string>} */
        const nodeToIdMap = new Map();

        /** @type {(id: string, node: Node) => void} */
        this.set = (id, node) => {
            if (!id || !node) {
                throw new Error("Id and Node cannot be nullish");
            }
            const oldNode = idToNodeMap.get(id);
            nodeToIdMap.delete(oldNode);
            const oldId = nodeToIdMap.get(node);
            idToNodeMap.delete(oldId);
            idToNodeMap.set(id, node);
            nodeToIdMap.set(node, id);
        };

        /** @type {(id: string) => Node | undefined} */
        this.getNode = (id) => idToNodeMap.get(id);

        /** @type {(node: Node) => string | undefined} */
        this.getId = (node) => nodeToIdMap.get(node);

        /** @type {(node: Node) => boolean} */
        this.hasNode = (node) => nodeToIdMap.has(node);
    }
}
