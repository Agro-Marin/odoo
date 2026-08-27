// @ts-check
/** @odoo-module native */

/** @typedef {any} Condition */
/** @typedef {any} Connector */
/** @typedef {any} Tree */
/** @typedef {any} Value */
/**
 * @import { ValueEditorInfo } from "@web/components/tree_editor/tree_editor_value_editors"
 */
/**
 * @import { OperatorEditorInfo } from "@web/components/tree_editor/tree_editor_operator_editor"
 */

import { Component, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import {
    getDefaultValue,
    getValueEditorInfo,
} from "@web/components/tree_editor/tree_editor_value_editors";
import { parseExpr } from "@web/core/py_js/py";
import { cloneTree, connector, isTree, TRUE_TREE } from "@web/core/tree/condition_tree";
import { getResModel } from "@web/core/tree/utils";
import { areEquivalentTrees } from "@web/core/tree/virtual_operators";
import { shallowEqual } from "@web/core/utils/collections/objects";
import { KeepLast, SupersededError } from "@web/core/utils/concurrency";
import { useService } from "@web/core/utils/hooks";

/**
 * @type {WeakMap<object, string>}
 */
const NODE_KEYS = new WeakMap();
let nextNodeKey = 0;

export class TreeEditor extends Component {
    static template = "web.TreeEditor";
    static components = {
        Dropdown,
        DropdownItem,
        TreeEditor,
    };
    static props = {
        tree: Object,
        resModel: String,
        update: Function,
        getDefaultCondition: Function,
        getPathEditorInfo: Function,
        getOperatorEditorInfo: Function,
        getDefaultOperator: Function,
        readonly: { type: Boolean, optional: true },
        slots: { type: Object, optional: true },
        isDebugMode: { type: Boolean, optional: true },
        defaultConnector: {
            type: [{ value: "&" }, { value: "|" }],
            optional: true,
        },
        isSubTree: { type: Boolean, optional: true },
    };
    static defaultProps = {
        defaultConnector: "&",
        readonly: false,
        isSubTree: false,
    };

    /** @type {import("services").ServiceFactories["field"]} */
    fieldService;

    /** @type {import("@web/core/utils/concurrency").KeepLast} */
    keepLastInfo;
    /** @type {import("services").ServiceFactories["tree_processor"]} */
    treeProcessor;

    /**
     * The tree this component edits: a clone of `props.tree`, normalised to a
     * connector at the root so that every edit has somewhere to attach.
     * @type {Tree}
     */
    tree;
    /**
     * The previous clone, kept so an equivalent update can reuse it and leave the
     * editor's node identities - and therefore its DOM - alone.
     * @type {Tree | null}
     */
    previousTree;
    /** @type {(path: any) => any} */
    getFieldDef;
    /** @type {((node: any) => string) | undefined} */
    getConditionDescription;
    /** @type {Condition} */
    defaultCondition;

    setup() {
        this.isTree = isTree;
        this.fieldService = useService("field");
        this.treeProcessor = useService("tree_processor");
        this.keepLastInfo = new KeepLast({ rejectSuperseded: true });
        onWillStart(() => this.onPropsUpdated(this.props));
        onWillUpdateProps((nextProps) => this.onPropsUpdated(nextProps));
    }

    /**
     * @param {Object} props
     */
    async onPropsUpdated(props) {
        if (this.tree) {
            this.previousTree = this.tree;
        }
        this.tree = cloneTree(props.tree);
        if (shallowEqual(this.tree, TRUE_TREE)) {
            this.tree = connector(props.defaultConnector);
        } else if (this.tree.type !== "connector") {
            this.tree = connector(props.defaultConnector, [this.tree]);
        }

        if (this.previousTree && areEquivalentTrees(this.tree, this.previousTree)) {
            this.tree = this.previousTree;
            this.previousTree = null;
        }

        await this.prepareInfo(props);
    }

    /**
     * @param {Object} props
     * @returns {Promise<boolean>}
     */
    async prepareInfo(props) {
        let loaded;
        try {
            loaded = await this.keepLastInfo.add(
                Promise.all([
                    this.fieldService.loadFields(props.resModel),
                    this.treeProcessor.makeGetFieldDef(props.resModel, this.tree),
                    props.readonly
                        ? this.treeProcessor.makeGetConditionDescription(
                              props.resModel,
                              this.tree,
                          )
                        : undefined,
                ]),
            );
        } catch (error) {
            if (error instanceof SupersededError) {
                return false;
            }
            throw error;
        }
        const [fieldDefs, getFieldDef, getConditionDescription] = loaded;
        this.getFieldDef = getFieldDef;
        this.defaultCondition = props.getDefaultCondition(fieldDefs);

        if (props.readonly) {
            this.getConditionDescription = getConditionDescription;
        }
        return true;
    }

    /**
     * @param {Tree} node
     * @returns {string}
     */
    getNodeKey(node) {
        let key = NODE_KEYS.get(node);
        if (key === undefined) {
            key = `node_${++nextNodeKey}`;
            NODE_KEYS.set(node, key);
        }
        return key;
    }

    /** @returns {string} */
    get className() {
        return this.props.readonly ? "o_read_mode" : "o_edit_mode";
    }

    /** @returns {boolean} */
    get isDebugMode() {
        return this.props.isDebugMode !== undefined
            ? this.props.isDebugMode
            : !!this.env.debug;
    }

    notifyChanges() {
        this.props.update(this.tree);
    }

    /**
     * @param {Connector} node
     */
    _updateConnector(node) {
        node.value = node.value === "&" ? "|" : "&";
        node.negate = false;
    }

    /**
     * @param {Connector} node
     */
    updateConnector(node) {
        return this.updateNode(node, () => this._updateConnector(node));
    }

    /**
     * @param {import("@web/core/tree/condition_tree").ComplexCondition} node
     * @param {string} value
     */
    _updateComplexCondition(node, value) {
        try {
            parseExpr(value);
        } catch {
            return;
        }
        node.value = value;
    }

    /**
     * @param {import("@web/core/tree/condition_tree").ComplexCondition} node
     * @param {string} value
     * @param {HTMLInputElement} [inputEl]
     */
    updateComplexCondition(node, value, inputEl) {
        // Not awaited: `_updateComplexCondition` is synchronous, so the node has
        // already accepted or refused the expression by the time updateNode yields,
        // and the box has to be corrected in the same tick as the change event.
        const applied = this.updateNode(node, () =>
            this._updateComplexCondition(node, value),
        );
        if (inputEl && inputEl.value !== node.value) {
            inputEl.value = node.value;
        }
        return applied;
    }

    /**
     * @param {Connector} parent
     * @param {Condition} [condition]
     * @returns {Tree}
     */
    makeCondition(parent, condition) {
        condition ||=
            parent.children.findLast((c) => c.type === "condition") ||
            this.defaultCondition;
        return cloneTree(condition);
    }

    /**
     * @param {Connector} parent
     * @param {Tree} [node]
     */
    _addNewCondition(parent, node) {
        const index = node ? parent.children.indexOf(node) : -1;
        if (index === -1) {
            parent.children.push(this.makeCondition(parent, node));
        } else {
            parent.children.splice(index + 1, 0, this.makeCondition(parent, node));
        }
    }

    /**
     * @param {Connector} parent
     * @param {Tree} [node]
     */
    addNewCondition(parent, node) {
        return this.updateNode(parent, () => this._addNewCondition(parent, node));
    }

    /**
     * @param {Connector} parent
     * @param {Tree} node
     */
    _addNewConnector(parent, node) {
        const index = parent.children.indexOf(node);
        const nextConnector = parent.value === "&" ? "|" : "&";
        const newConnector = connector(nextConnector, [
            this.makeCondition(parent, node),
        ]);
        if (index === -1) {
            parent.children.push(newConnector);
        } else {
            parent.children.splice(index + 1, 0, newConnector);
        }
    }

    /**
     * @param {Connector} parent
     * @param {Tree} node
     */
    addNewConnector(parent, node) {
        return this.updateNode(parent, () => this._addNewConnector(parent, node));
    }

    /**
     * @param {Connector[]} ancestors
     * @param {Tree} node
     */
    _delete(ancestors, node) {
        if (!ancestors.length) {
            return;
        }
        const parent = ancestors.at(-1);
        const index = parent.children.indexOf(node);
        if (index === -1) {
            return;
        }
        parent.children.splice(index, 1);
        ancestors = ancestors.slice(0, -1);
        if (!parent.children.length) {
            this._delete(ancestors, parent);
        }
    }

    /**
     * @param {Connector[]} ancestors
     * @param {Tree} node
     */
    delete(ancestors, node) {
        const upperNode = ancestors[0] || node;
        return this.updateNode(upperNode, () => this._delete(ancestors, node));
    }

    /**
     * @param {Condition} node
     * @returns {string|null}
     */
    getResModel(node) {
        return getResModel(this.getFieldDef(node.path));
    }

    /** @returns {Object} */
    getPathEditorInfo() {
        return this.props.getPathEditorInfo(this.props.resModel, this.defaultCondition);
    }

    /**
     * @param {Condition} node
     * @returns {OperatorEditorInfo}
     */
    getOperatorEditorInfo(node) {
        const fieldDef = this.getFieldDef(node.path);
        return this.props.getOperatorEditorInfo(fieldDef);
    }

    /**
     * @param {Condition} node
     * @returns {ValueEditorInfo}
     */
    getValueEditorInfo(node) {
        const fieldDef = this.getFieldDef(node.path);
        return getValueEditorInfo(fieldDef, node.operator);
    }

    /**
     * @param {Condition} node
     * @param {string} path
     */
    async _updatePath(node, path) {
        const { fieldDef } = await this.fieldService.loadFieldInfo(
            this.props.resModel,
            path,
        );
        node.path = path;
        node.negate = false;
        node.operator = this.props.getDefaultOperator(fieldDef);
        node.value = getDefaultValue(fieldDef, node.operator);
        node.isProperty = fieldDef?.is_property;
    }

    /**
     * @param {Condition} node
     * @param {string} path
     */
    async updatePath(node, path) {
        return this.updateNode(node, () => this._updatePath(node, path));
    }

    /**
     * @param {Condition} node
     * @param {Value} operator
     * @param {boolean} negate
     */
    _updateLeafOperator(node, operator, negate) {
        const fieldDef = this.getFieldDef(node.path);
        node.negate = negate;
        node.operator = operator;
        node.value = getDefaultValue(fieldDef, operator, node.value);
    }

    /**
     * @param {Condition} node
     * @param {Value} operator
     * @param {boolean} negate
     */
    updateLeafOperator(node, operator, negate) {
        return this.updateNode(node, () =>
            this._updateLeafOperator(node, operator, negate),
        );
    }

    /**
     * @param {Condition} node
     * @param {any} value
     */
    _updateLeafValue(node, value) {
        node.value = value;
    }

    /**
     * @param {Condition} node
     * @param {any} value
     */
    updateLeafValue(node, value) {
        return this.updateNode(node, () => this._updateLeafValue(node, value));
    }

    /**
     * Applies one edit to the tree and reports it upward. Every public wrapper
     * returns this: `_updatePath` awaits the field service, so a rejection there
     * has nowhere to go if the promise is dropped.
     *
     * @param {Tree} node
     * @param {() => void|Promise<void>} operation
     * @returns {Promise<void>}
     */
    async updateNode(node, operation) {
        const previousNode = cloneTree(node);
        await operation();
        const parentWillNotRerenderUs = areEquivalentTrees(node, previousNode);
        if (parentWillNotRerenderUs && (await this.prepareInfo(this.props))) {
            this.render();
        }
        this.notifyChanges();
    }

    /**
     * @param {HTMLElement} target
     * @param {boolean} force
     */
    highlightNode(target, force) {
        target
            .closest(".o_tree_editor_node")
            ?.classList.toggle("o_hovered_button", force);
    }
}
