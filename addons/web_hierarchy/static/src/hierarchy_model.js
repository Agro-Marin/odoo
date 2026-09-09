/** @odoo-module native */
import { toRaw } from "@odoo/owl";
import { Domain } from "@web/core/domain";
import { _t } from "@web/core/translation";
import { KeepLast, Mutex } from "@web/core/utils/concurrency";
import { Model } from "@web/model/model";
import { getFieldsSpec } from "@web/model/relational_model";
import { orderByToString } from "@web/core/utils/order_by";

/**
 * Get the id of the given many2one field value
 *
 * @param {false | {id: Number, display_name?: String}} value many2one value, as
 *        returned by web_read
 * @returns {false | Number} id of the many2one
 */
function getIdOfMany2oneField(value) {
    return value ? value.id : false;
}

/**
 * Deduplicate records by their id, keeping the first occurrence.
 *
 * @param {Object[]} records
 * @returns {Object[]}
 */
function uniqueById(records) {
    return [...new Map(records.map((record) => [record.id, record])).values()];
}

export class HierarchyNode {
    /**
     * Constructor of hierarchy node stored in hierarchy tree
     *
     * @param {HierarchyModel} model
     * @param {Object} config
     * @param {Object} data
     * @param {HierarchyTree} tree
     * @param {HierarchyNode} parentNode
     * @param {Boolean} populateChildNodes
     */
    constructor(
        model,
        config,
        data,
        tree,
        parentNode = null,
        populateChildNodes = true,
    ) {
        this.id = model.nextNodeId();
        this.data = data;
        this.parentNode = parentNode;
        this.tree = tree;
        this.model = model;
        this._config = config;
        this.hidden = false;
        tree.addNode(this);
        if (populateChildNodes) {
            this.populateChildNodes();
        }
    }

    /**
     * Is leaf?
     *
     * @returns {Boolean} False if the current node has node as child nodes, otherwise True.
     */
    get isLeaf() {
        return !this.nodes.length;
    }

    /**
     * Get forest of the current node
     *
     * @returns {HierarchyForest}
     */
    get forest() {
        return this.tree.forest;
    }

    /**
     * Get the resId of current node
     *
     * @returns {Number}
     */
    get resId() {
        return this.data.id;
    }

    /**
     * Get parent field name
     *
     * @returns {String}
     */
    get parentFieldName() {
        return this.model.parentFieldName;
    }

    /**
     * Get parent res id
     *
     * @returns {Number}
     */
    get parentResId() {
        return (
            this.parentNode?.resId ||
            getIdOfMany2oneField(this.data[this.parentFieldName])
        );
    }

    /**
     * Get child node res ids
     *
     * @returns {Number[]}
     */
    get childResIds() {
        return this._nodes.length
            ? this._nodes.map((node) => node.resId)
            : this.data[this.childFieldName]?.map((d) =>
                  typeof d === "number" ? d : d.id,
              ) || [];
    }

    /**
     * Get child field name
     *
     * @returns {String}
     */
    get childFieldName() {
        return this.model.childFieldName;
    }

    /**
     * Has child nodes?
     *
     * @returns {Boolean}
     */
    get hasChildren() {
        return this._nodes.length > 0 || this.data[this.childFieldName]?.length > 0;
    }

    /**
     * Is the record of this node displayed exactly once in the whole forest?
     *
     * A record reached through two branches (a cycle, or a record that is both a
     * root and someone's child) is rendered as two nodes sharing one `data`
     * object. Expanding or collapsing either copy would desynchronise them, so
     * both are frozen.
     *
     * @returns {Boolean}
     */
    get isOnlyOccurrenceOfItsRecord() {
        return this.forest.isResIdUnique(this.resId);
    }

    /**
     * Can show parent node
     *
     * Knows if the parent node can be fetched and displayed inside the view
     *
     * @returns {Boolean} True if the current node has a parent node but it is not yet displayed and the data of the
     *                    current node is not already displayed in another node.
     */
    get canShowParentNode() {
        return (
            Boolean(this.parentResId) &&
            this.parentResId !== this.resId &&
            !this.parentNode &&
            this.isOnlyOccurrenceOfItsRecord
        );
    }

    /**
     * Can show child nodes
     *
     * Knows if the child nodes can be fetched and displayed inside the view
     *
     * @returns {Boolean} True if the current node has child nodes but they are not yet displayed and the data of the
     *                    current node is not already displayed in another node.
     */
    get canShowChildNodes() {
        return (
            this.hasChildren &&
            this.nodes.length === 0 &&
            this.isOnlyOccurrenceOfItsRecord
        );
    }

    getDescendantNodes(hideNodesIncluded = false) {
        const subNodes = [];
        const nodes = hideNodesIncluded ? this._nodes : this.nodes;
        for (const node of nodes) {
            subNodes.push(node, ...node.getDescendantNodes(hideNodesIncluded));
        }
        return subNodes;
    }

    /**
     * Get all descendants nodes parents. If the current node has descendants,
     * it is also included in the result.
     *
     * @returns {HierarchyNode[]} contains descendants parents in order of depth
     *          (closest to root first).
     */
    get descendantsParentNodes() {
        if (this.isLeaf) {
            return [];
        }
        const parentNodes = [this];
        for (const node of this.nodes) {
            parentNodes.push(...node.descendantsParentNodes);
        }
        return parentNodes;
    }

    /**
     * Get all descendants nodes resIds
     *
     * @returns {Number[]}
     */
    get allSubsidiaryResIds() {
        return this.getDescendantNodes().map((n) => n.resId);
    }

    get nodes() {
        return this._nodes.filter((n) => !n.hidden);
    }

    /**
     * Populate child nodes
     *
     * Uses to create child nodes of the current one according to its data.
     */
    populateChildNodes() {
        this._nodes = [];
        const children = this.data[this.childFieldName] || [];
        if (
            children.length &&
            children[0] instanceof Object &&
            this.isOnlyOccurrenceOfItsRecord
        ) {
            this.createChildNodes(children);
        }
    }

    /**
     * create child nodes
     *
     * @param {Object[]} childNodesData data of child nodes to generate
     */
    createChildNodes(childNodesData) {
        this._nodes = (childNodesData || this.data[this.childFieldName]).map(
            (childData) =>
                new HierarchyNode(this.model, this._config, childData, this.tree, this),
        );
    }

    removeParentNode() {
        this.parentNode?.removeChildNode(this);
        this.parentNode = null;
        this.data[this.parentFieldName] = false;
    }

    /**
     * Fetch parent node
     */
    async fetchParentNode() {
        await this.model.fetchManager(this);
    }

    /**
     * Fetch child nodes
     */
    async showChildNodes() {
        if (!this.hasChildren) {
            return;
        }
        if (!this._nodes.length) {
            await this.model.fetchSubordinates(this);
            return;
        }
        this.model._searchNodeToCollapse(this)?.collapseChildNodes(true);
        for (const node of this.getDescendantNodes(true)) {
            node.hidden = false;
            this.tree.addNode(node);
        }
        this.model.notify();
    }

    /**
     * Collapse child nodes
     *
     * Removes the descendant nodes of the current one and stores
     * the resIds of the child nodes in the data of the current one
     * to know it has child nodes to be able to show them again
     * when it is needed.
     *
     * @param hideNodes: hide the descendants when it is true to keep the data in cache (default: false)
     */
    collapseChildNodes(hideNodes = false) {
        if (hideNodes) {
            const nodesToHide = this.getDescendantNodes();
            for (const node of nodesToHide) {
                node.hidden = true;
            }
            this.tree.removeNodes(nodesToHide);
        } else {
            const childrenData = [];
            for (const childNode of this.nodes) {
                childNode.data[this.childFieldName] = childNode.childResIds;
                childrenData.push(childNode.data);
            }
            this.data[this.childFieldName] = childrenData;
            this.removeChildNodes();
        }
        this.model.notify();
    }

    removeChildNode(node) {
        node.removeChildNodes();
        this.tree.removeNodes([node]);
        this._nodes = this._nodes.filter((n) => n.id !== node.id);
        this.data[this.childFieldName] = this._nodes.map((n) => n.data);
    }

    /**
     * Remove descendant nodes of the current one
     */
    removeChildNodes(rootNode = this) {
        for (const childNode of this.nodes) {
            if (!childNode.isLeaf && childNode !== rootNode) {
                childNode.removeChildNodes(rootNode);
            }
        }
        this.tree.removeNodes(this._nodes);
        this._nodes = [];
    }

    /**
     * Set parent node to the current node
     *
     * @param {HierarchyNode} node parent node to set
     */
    setParentNode(node) {
        const tree = node.tree;
        if (tree.root === this) {
            tree.root = node;
        } else if (this.tree.root === this) {
            this.tree.removeRoot();
            this.setTree(node.tree);
        }
        this.parentNode = node;
        node.addChildNode(this);
    }

    /**
     * Move the current node and its descendants into another tree, and register
     * them there. Hidden descendants stay out of the tree index, exactly as they
     * were in the tree they are leaving.
     *
     * @param {HierarchyTree} tree
     */
    setTree(tree) {
        this.tree = tree;
        if (!this.hidden) {
            tree.addNode(this);
        }
        for (const childNode of this._nodes) {
            childNode.setTree(tree);
        }
    }

    /**
     * Adds child node to the current node
     *
     * @param {HierarchyNode} node child node to add
     */
    addChildNode(node) {
        this._nodes.push(node);
        this.data[this.childFieldName].push(node.data);
        this.tree.addNode(node);
    }
}

export class HierarchyTree {
    /**
     * Constructor
     *
     * @param {HierarchyModel} model
     * @param {Object} config config of the model
     * @param {Object} data root node data of the tree to create
     * @param {HierarchyForest} forest hierarchy forest containing the tree to create
     */
    constructor(model, config, data, forest) {
        this.id = model.nextTreeId();
        this.model = model;
        this._config = config;
        this.forest = forest;
        this.nodePerNodeId = new Map();
        if (data) {
            this.root = new HierarchyNode(model, config, data, this);
        }
    }

    /**
     * Get node res ids inside the current tree
     *
     * @returns {Number[]}
     */
    get resIds() {
        return [...this.nodePerNodeId.values()].map((node) => node.resId);
    }

    /**
     * Add node inside the current tree
     *
     * @param {HierarchyNode} node node to add inside the current tree
     */
    addNode(node) {
        this.nodePerNodeId.set(node.id, node);
        this.forest.addNode(node);
    }

    /**
     * Remove nodes inside the current tree
     *
     * @param {HierarchyNode[]} nodes nodes to remove
     */
    removeNodes(nodes) {
        for (const node of nodes) {
            this.nodePerNodeId.delete(node.id);
        }
        this.forest.removeNodes(nodes);
    }

    removeRoot() {
        this.forest.removeTree(this);
    }
}

export class HierarchyForest {
    /**
     *
     * @param {HierarchyModel} model
     * @param {Object} config model config
     * @param {Object[]} data list of tree root nodes data
     */
    constructor(model, config, data) {
        this.id = model.nextForestId();
        this.model = model;
        this._config = config;
        this.nodePerNodeId = new Map();
        this._nodeCountPerResId = new Map();
        this._trees = data.map((d) => new HierarchyTree(model, config, d, this));
    }

    get trees() {
        return this._trees.filter((t) => !t.root.hidden);
    }

    /**
     * Get node res ids containing inside the current forest
     *
     * @returns {Number[]}
     */
    get resIds() {
        return [...this.nodePerNodeId.values()].map((node) => node.resId);
    }

    /**
     * Get root node of all trees inside the current forest
     *
     * @returns {HierarchyNode[]} root nodes
     */
    get rootNodes() {
        return this.trees.map((t) => t.root);
    }

    /**
     * Is the given record displayed by exactly one node of this forest?
     *
     * @param {Number} resId
     * @returns {Boolean}
     */
    isResIdUnique(resId) {
        return this._nodeCountPerResId.get(resId) === 1;
    }

    /**
     * Add a node inside the current forest
     *
     * @param {HierarchyNode} node node to add inside the current forest
     */
    addNode(node) {
        if (this.nodePerNodeId.has(node.id)) {
            return;
        }
        this.nodePerNodeId.set(node.id, node);
        this._nodeCountPerResId.set(
            node.resId,
            (this._nodeCountPerResId.get(node.resId) || 0) + 1,
        );
    }

    /**
     * Removes nodes inside the current forest
     *
     * @param {HierarchyNode[]} nodes nodes to remove inside the current forest
     */
    removeNodes(nodes) {
        for (const node of nodes) {
            if (!this.nodePerNodeId.delete(node.id)) {
                continue;
            }
            const remaining = this._nodeCountPerResId.get(node.resId) - 1;
            if (remaining > 0) {
                this._nodeCountPerResId.set(node.resId, remaining);
            } else {
                this._nodeCountPerResId.delete(node.resId);
            }
        }
    }

    removeTree(tree) {
        this.removeNodes([...tree.nodePerNodeId.values()]);
        this._trees = this._trees.filter((t) => t.id !== tree.id);
    }
}

export class HierarchyModel extends Model {
    static services = ["notification"];

    setup(params, { notification }) {
        this.keepLast = new KeepLast();
        this.mutex = new Mutex();
        this.resModel = params.resModel;
        this.fields = params.fields;
        this.parentFieldName = params.parentFieldName;
        this.declaredChildFieldName = params.childFieldName;
        this.activeFields = params.activeFields;
        this.defaultOrderBy = params.defaultOrderBy;
        this.notification = notification;
        this._nodeId = 0;
        this._treeId = 0;
        this._forestId = 0;
        this.config = {
            domain: [],
            ...params.config,
            isRoot: true,
        };
    }

    nextNodeId() {
        return this._nodeId++;
    }

    nextTreeId() {
        return this._treeId++;
    }

    nextForestId() {
        return this._forestId++;
    }

    /**
     * Get parent field info
     *
     * @returns {Object} parent field info
     */
    get parentField() {
        return this.fields[this.parentFieldName];
    }

    /**
     * Get res ids of all nodes displayed in the view
     *
     * @returns {Number[]} resIds of all nodes displayed in the view
     */
    get resIds() {
        return this.root?.resIds || [];
    }

    /**
     * Get default child field name when no child field name is given to the view
     *
     * @returns {String} default child field name to use
     */
    get defaultChildFieldName() {
        return "__child_ids__";
    }

    /**
     * Name of the key holding the children of a record, either the one2many
     * declared by the view or the one @see hierarchy_read synthesises.
     *
     * @returns {String}
     */
    get childFieldName() {
        return this.declaredChildFieldName || this.defaultChildFieldName;
    }

    /**
     * Get default domain to use, when no domain is given in the config
     *
     * @returns {import("@web/core/domain").DomainListRepr} default domain
     */
    get defaultDomain() {
        return [[this.parentFieldName, "=", false]];
    }

    /**
     * Get the global domain of the view (which is the domain defined on the
     * view without applying filters).
     *
     * @returns {import("@web/core/domain").DomainListRepr} global domain
     */
    get globalDomain() {
        if (!this.env.searchModel?.globalDomain.length) {
            return [];
        }
        return new Domain(this.env.searchModel.globalDomain).toList(
            this.env.searchModel.domainEvalContext,
        );
    }

    /**
     * Get active fields name
     *
     * @returns {String[]} active fields name
     */
    get activeFieldNames() {
        return Object.keys(this.activeFields);
    }

    get context() {
        return {
            bin_size: true,
            ...(this.config.context || {}),
        };
    }

    exportState() {
        return {
            config: toRaw({
                ...this.config,
                resIds: this.resIds,
            }),
        };
    }

    /**
     * Load the config and data for hierarchy view
     *
     * @param {Object} params params to use to load data of hierarchy view
     */
    async load(params = {}) {
        const { resIds, ...config } = this._getNextConfig(this.config, params);
        const data = await this.keepLast.add(this._loadData({ ...config, resIds }));
        this.root = this._createRoot(config, data);
        this.config = config;
        this.notify({ scrollTarget: "none" });
    }

    /**
     * Reload the current view with all currently loaded records
     */
    async reload() {
        const data = await this.keepLast.add(this._loadData(this.config, true));
        this.root = this._createRoot(this.config, data);
        this.notify({ scrollTarget: "none" });
    }

    /**
     * @override
     * Each notify should specify a scroll target (default is to scroll to the
     * bottom).
     */
    notify(payload = { scrollTarget: "bottom" }) {
        super.notify();
        this.bus.trigger("hierarchyScrollTarget", payload);
    }

    /**
     * Fetch parent node of given node
     * @param {HierarchyNode} node node to fetch its parent node
     */
    async fetchManager(node) {
        if (this.root.trees.length > 1) {
            // reset the hierarchy
            const treeExpanded = this._findTreeExpanded();
            const resIdsToFetch = [
                node.parentResId,
                node.resId,
                ...node.allSubsidiaryResIds,
            ];
            if (
                treeExpanded &&
                treeExpanded.root.id !== node.id &&
                treeExpanded.root.parentResId === node.parentResId
            ) {
                resIdsToFetch.push(...treeExpanded.root.allSubsidiaryResIds);
            }
            const config = {
                ...this.config,
                domain: [
                    "|",
                    [this.parentFieldName, "=", node.parentResId],
                    ["id", "in", resIdsToFetch],
                ],
            };
            const data = await this._loadData(config);
            this.root = this._createRoot(config, data);
            this.notify();
            return;
        }
        const managerData = await this.keepLast.add(this._fetchManager(node));
        if (managerData) {
            const parentNode = new HierarchyNode(
                this,
                this.config,
                managerData,
                node.tree,
                null,
                false,
            );
            parentNode.createChildNodes();
            node.setParentNode(parentNode);
            this.notify({ scrollTarget: "up" });
        }
    }

    /**
     * Fetch child nodes of given node
     *
     * @param {HierarchyNode} node node to fetch its child nodes
     */
    async fetchSubordinates(node) {
        const childFieldName = this.childFieldName;
        const children = node.data[childFieldName];
        if (!children?.length) {
            return;
        }
        const nodesToUpdate = [];
        if (!(children[0] instanceof Object)) {
            const allNodeResIds = this.root.resIds;
            let existingChildResIds = children.filter((childResId) =>
                allNodeResIds.includes(childResId),
            );
            if (existingChildResIds.length) {
                // special case with result found with the search view
                for (const tree of this.root.trees) {
                    if (
                        existingChildResIds.includes(tree.root.resId) &&
                        tree.root.id !== node.id
                    ) {
                        // don't re-root if both nodes are in the same tree
                        if (node.tree.id === tree.id) {
                            existingChildResIds = existingChildResIds.filter(
                                (resId) => resId !== tree.root.resId,
                            );
                            continue;
                        }
                        nodesToUpdate.push(tree.root);
                    }
                }
            }
            const subordinates = await this.keepLast.add(
                this._fetchSubordinates(node, existingChildResIds),
            );
            if (subordinates.length) {
                node.data[childFieldName] = subordinates;
            }
        }
        const nodeToCollapse = this._searchNodeToCollapse(node);
        if (nodeToCollapse && !nodesToUpdate.includes(nodeToCollapse)) {
            nodeToCollapse.collapseChildNodes(true);
        }
        node.populateChildNodes();
        for (const n of nodesToUpdate) {
            n.setParentNode(node);
        }
        this.notify();
    }

    /**
     * Search node to collapse to be able to show the child nodes of node given in parameter
     *
     * @param {HierarchyNode} node node to show its child nodes.
     * @returns {HierarchyNode | null} node found to collapse
     */
    _searchNodeToCollapse(node) {
        const parentNode = node.parentNode;
        if (parentNode) {
            return parentNode.nodes.find((n) => n.nodes.length) || null;
        }
        return this._findTreeExpanded()?.root || null;
    }

    _findTreeExpanded() {
        return this.root.trees.find((t) => t.root.nodes.length);
    }

    /**
     * Get the next model config to use
     *
     * @param {Object} currentConfig current model config used
     * @param {Object} params new params
     * @returns {Object} new model config to use
     */
    _getNextConfig(currentConfig, params) {
        const config = Object.assign({}, currentConfig);
        config.context = "context" in params ? params.context : config.context;
        if ("domain" in params) {
            config.domain = params.domain;
            if (this.isSearchDefaultOrEmpty() && config.context?.hierarchy_res_id) {
                config.domain = [["id", "=", config.context.hierarchy_res_id]];
                const globalDomain = this.globalDomain;
                if (globalDomain.length) {
                    config.domain = Domain.and([config.domain, globalDomain]);
                }
                // Just needed for the first load.
                delete config.context.hierarchy_res_id;
            }
        }

        // orderBy
        config.orderBy = "orderBy" in params ? params.orderBy : config.orderBy;
        // re-apply previous orderBy if not given (or no order)
        if (!config.orderBy.length) {
            config.orderBy = currentConfig.orderBy || [];
        }
        // apply default order if no order
        if (this.defaultOrderBy && !config.orderBy.length) {
            config.orderBy = this.defaultOrderBy;
        }
        return config;
    }

    _getFieldsSpec(context = this.config.context) {
        return getFieldsSpec(this.activeFields, this.fields, context);
    }

    /**
     * Evaluate if the current search query is the default one.
     *
     * @returns {boolean}
     */
    isSearchDefaultOrEmpty() {
        if (!this.env.searchModel) {
            return true;
        }
        const isDisabledOptionalSearchMenuType = (type) => {
            return (
                ["filter", "groupBy", "favorite"].includes(type) &&
                !this.env.searchModel.searchMenuTypes.has(type)
            );
        };
        const activeSearchItems = this.env.searchModel.getSearchItems(
            (item) => item.isActive && !isDisabledOptionalSearchMenuType(item.type),
        );
        if (!activeSearchItems.length) {
            return true;
        }
        const defaultSearchItems = this.env.searchModel.getSearchItems(
            (item) =>
                item.isDefault &&
                item.type !== "favorite" &&
                !isDisabledOptionalSearchMenuType(item.type),
        );
        return (
            defaultSearchItems.length === activeSearchItems.length &&
            defaultSearchItems.every(
                (item, index) => item.id === activeSearchItems[index].id,
            )
        );
    }

    /**
     * Load data for hierarchy view
     *
     * @param {Object} config model config
     * @param {boolean} reload all currently loaded resIds instead of using
     *        the config domain
     * @returns {Object[]} main data for hierarchy view
     */
    async _loadData(config, reload = false) {
        const resIds = reload ? this.resIds : config.resIds;
        let onlyRoots = false;
        let domain = config.domain;
        if (resIds?.length > 0) {
            domain = [["id", "in", resIds]];
        } else if (this.isSearchDefaultOrEmpty()) {
            // If the current SearchModel query is the default one
            // configured for the action or there is no search query, an
            // additional constraint is added to only display "root"
            // records (without a parent).
            onlyRoots = true;
            domain = !domain.length
                ? this.defaultDomain
                : Domain.and([this.defaultDomain, domain]).toList({});
        }
        let result = await this._hierarchyRead(domain, config);
        if (!result.length && onlyRoots) {
            // No root matched: the records the user is after all have a parent,
            // so answer with them rather than with an empty view.
            result = await this._hierarchyRead(config.domain, config);
        }
        return this._formatData(result);
    }

    /**
     * @param {import("@web/core/domain").DomainListRepr} domain
     * @param {Object} config model config
     * @returns {Promise<Object[]>}
     */
    _hierarchyRead(domain, config) {
        return this.orm.call(
            this.resModel,
            "hierarchy_read",
            [
                domain,
                this._getFieldsSpec(config.context),
                this.parentFieldName,
                this.declaredChildFieldName,
                orderByToString(config.orderBy),
            ],
            { context: this.context },
        );
    }

    /**
     * Turn the flat record list returned by @see hierarchy_read into the list of
     * root records, each holding its children under the child field.
     *
     * The hierarchy renders one row per depth, so it can only nest a single
     * branch: when two records of the same level both have children in the
     * payload, the whole payload is returned flat instead.
     *
     * @param {Object[]} data
     * @returns {Object[]} root records
     */
    _formatData(data) {
        const childFieldName = this.childFieldName;
        const recordPerId = new Map();
        // The insertion order of this object drives the order of the roots
        // below: integer-like keys come out in ascending order and the "false"
        // key (the parentless records) last.
        const recordsPerParentId = {};
        for (const record of data) {
            recordPerId.set(record.id, record);
            const parentId = getIdOfMany2oneField(record[this.parentFieldName]);
            recordsPerParentId[parentId] ||= [];
            recordsPerParentId[parentId].push(record);
        }
        const rootRecords = [];
        const branches = [];
        // ids of the records sharing a level with a parent already collected in
        // `branches`: a second parent among them means a second arborescence.
        const siblingIdsOfCollectedParents = new Set();
        for (const [parentId, records] of Object.entries(recordsPerParentId)) {
            const parentRecord = recordPerId.get(Number(parentId));
            if (!parentRecord) {
                rootRecords.push(...uniqueById(records));
                continue;
            }
            if (siblingIdsOfCollectedParents.has(parentRecord.id)) {
                return data;
            }
            const ancestorId = getIdOfMany2oneField(parentRecord[this.parentFieldName]);
            for (const sibling of recordsPerParentId[ancestorId] || []) {
                siblingIdsOfCollectedParents.add(sibling.id);
            }
            branches.push([parentRecord, uniqueById(records)]);
        }
        for (const [parentRecord, children] of branches) {
            parentRecord[childFieldName] = children;
        }
        if (!rootRecords.length && branches.length) {
            // Every record has its parent in the payload: the hierarchy loops.
            // Start from the first parent so that something is displayed.
            rootRecords.push(branches[0][0]);
        }
        return rootRecords;
    }

    /**
     * Create forest
     *
     * @param {Object} config model config to use
     * @param {Object[]} data root data
     * @returns {HierarchyForest} forest hierarchy
     */
    _createRoot(config, data) {
        return new HierarchyForest(this, config, data);
    }

    /**
     * Fetch parent node and its children nodes data
     *
     * @param {HierarchyNode} node node to fetch its parent node
     * @returns {Object} the parent node data with children data inside childFieldName
     */
    async _fetchManager(node) {
        const domain = Domain.and([
            [
                "|",
                ["id", "=", node.parentResId],
                [this.parentFieldName, "=", node.parentResId],
            ],
            [["id", "!=", node.resId]],
        ]);
        const result = await this.orm.webSearchRead(this.resModel, domain.toList({}), {
            context: this.context,
            specification: this._getFieldsSpec(),
            order: orderByToString(this.config.orderBy),
        });
        let managerData = {};
        if (result?.length) {
            const children = [];
            for (const data of result.records) {
                if (data.id === node.parentResId) {
                    managerData = data;
                } else {
                    children.push(data);
                }
            }
            if (!this.declaredChildFieldName && children.length) {
                await this._fetchDescendants(children);
            }
            managerData[this.childFieldName] = children;
        }
        return managerData;
    }

    /**
     * Fetch children nodes data for a given node
     *
     * @param {HierarchyNode} node node to fetch its children nodes
     * @param {Array<number> | null} excludeResIds list of ids to exclude (because the nodes already exist)
     * @returns {Object[]} list of child node data
     */
    async _fetchSubordinates(node, excludeResIds = null) {
        let childrenResIds = node.data[this.childFieldName];
        if (excludeResIds) {
            childrenResIds = childrenResIds.filter(
                (childResId) => !excludeResIds.includes(childResId),
            );
        }
        if (!childrenResIds.length) {
            return [];
        }
        const { records } = await this.orm.webSearchRead(
            this.resModel,
            [["id", "in", childrenResIds]],
            {
                specification: this._getFieldsSpec(),
                context: this.context,
                order: orderByToString(this.config.orderBy),
            },
        );
        if (!this.declaredChildFieldName) {
            await this._fetchDescendants(records);
        }
        return records;
    }

    /**
     * fetch descendants nodes resIds to know if the child nodes have descendants
     *
     * @param {Object[]} childrenData child nodes data to fetch its descendants
     */
    async _fetchDescendants(childrenData) {
        const resIds = childrenData.map((d) => d.id);
        if (!resIds.length) {
            return;
        }
        // No `order`: the aggregate below groups on the parent field only, and
        // formatted_read_group refuses an order term that is neither a groupby
        // nor an aggregate. The children are ordered when they are read.
        const fetchChildren = await this.orm.formattedReadGroup(
            this.resModel,
            [[this.parentFieldName, "in", resIds]],
            [this.parentFieldName],
            ["id:array_agg"],
            { context: this.context },
        );
        const childIdsPerId = new Map(
            fetchChildren.map((g) => [g[this.parentFieldName][0], g["id:array_agg"]]),
        );
        for (const d of childrenData) {
            if (childIdsPerId.has(d.id)) {
                d[this.childFieldName] = childIdsPerId.get(d.id);
            }
        }
    }

    /**
     * ORM call to update the parentId of a record during @see updateParentNode
     * Can be overridden to not use "write".
     *
     * @param {HierarchyNode} node node related to the record which parentId
     *        should be changed
     * @param {Number} parentResId id of the new parent record
     */
    async updateParentId(node, parentResId = false) {
        return this.orm.write(
            this.resModel,
            [node.resId],
            { [this.parentFieldName]: parentResId },
            { context: this.context },
        );
    }

    /**
     * @param {Number} nodeId of the node to update
     * @param {Object} parentInfo
     * @param {Number} [parentInfo.parentNodeId] nodeId of the parent
     * @param {Number | false} [parentInfo.parentResId] resId of the parent
     * @returns {Promise}
     */
    async updateParentNode(nodeId, { parentNodeId, parentResId }) {
        const node = this.root.nodePerNodeId.get(nodeId);
        if (!node) {
            return;
        }
        const resId = node.resId;
        const parentNode =
            parentNodeId === undefined
                ? null
                : this.root.nodePerNodeId.get(parentNodeId) || null;
        parentResId = parentResId || parentNode?.resId || false;
        const oldParentNode = node.parentNode;
        if (
            (parentNode && !this.validateUpdateParentNode(node, parentNode)) ||
            parentNode?.resId === oldParentNode?.resId
        ) {
            return;
        }
        // Hide the node while waiting for the server response.
        node.hidden = true;
        this.notify({ scrollTarget: "none" });
        // Update the parent server side.
        await this.mutex.exec(async () => {
            try {
                await this.updateParentId(node, parentResId);
            } catch (error) {
                // Show the node again since the operation failed, don't update the view.
                node.hidden = false;
                this.notify({ scrollTarget: "none" });
                throw error;
            }
        });
        // Reload impacted records.
        const domain = this.computeUpdateParentNodeDomain(
            node,
            parentResId,
            parentNode,
        );
        const data = await this.orm.webSearchRead(this.resModel, domain, {
            specification: this._getFieldsSpec(),
            context: this.context,
            order: orderByToString(this.config.orderBy),
        });
        if (!data.length) {
            return this.reload();
        }
        const formattedData = this._formatData(data.records);
        // Validate that data coming from the server is still compatible with the current
        // configuration of the hierarchy.
        for (const record of formattedData) {
            if (getIdOfMany2oneField(record[this.parentFieldName]) !== parentResId) {
                node.hidden = false;
                this.notify({ scrollTarget: "none" });
                this.notification.add(
                    _t(
                        `The parent of "%s" was successfully updated. Reloading records to account for other changes.`,
                        node.data.display_name || node.data.name,
                    ),
                    { type: "success" },
                );
                return this.reload();
            }
        }
        const nodeToCollapse = this._searchNodeToCollapseAfterMove(node, parentNode);
        // Update the view.
        if (oldParentNode) {
            oldParentNode.removeChildNode(node);
        } else {
            // `node` was the root of its tree: drop the tree with it, otherwise
            // the forest keeps a tree nothing renders.
            node.tree.removeRoot();
        }
        nodeToCollapse?.collapseChildNodes();
        if (!parentNode) {
            // Drop as root, reset the hierarchy.
            this.root = this._createRoot(this.config, formattedData);
        } else {
            // Update parentNode data.
            parentNode.data[this.childFieldName] = formattedData;
            parentNode.populateChildNodes();
        }
        const newNode = [...this.root.nodePerNodeId.values()].find(
            (n) => n.resId === resId,
        );
        this.notify({ scrollTarget: newNode?.id });
    }

    /**
     * Which node of the currently expanded tree has to be collapsed so that the
     * tree stays a single branch once `node` has moved under `parentNode`.
     *
     * @param {HierarchyNode} node that is moving
     * @param {HierarchyNode} [parentNode] which receives node as its child
     *                        (undefined if node is dropped as a root).
     * @returns {HierarchyNode | undefined} node to collapse
     */
    _searchNodeToCollapseAfterMove(node, parentNode) {
        const treeExpanded = this._findTreeExpanded();
        const expandedParentNodeIds =
            treeExpanded?.root.descendantsParentNodes.map((n) => n.id) || [];
        if (node.isLeaf && expandedParentNodeIds.includes(parentNode?.id)) {
            // node is a leaf dropped in the current expanded tree: the tree is
            // kept open. Descendants of parentNode will always be reloaded to
            // account for changes caused by the drop operation.
            return parentNode;
        }
        // The expanded tree will be altered. If node is not a leaf, the new
        // expanded tree will contain its descendants. If parentNode is not a
        // parent in the current expanded tree, it will become one in the new
        // expanded tree. Compute the depth of the parent of parentNode. That
        // node is guaranteed to be a parent in the current expanded tree.
        const depth = expandedParentNodeIds.indexOf(parentNode?.parentNode?.id);
        if (depth === -1) {
            // Drop as root or drop as the child of a root that is not part of
            // the current expanded tree. The current expanded tree should be
            // fully closed.
            return treeExpanded?.root;
        }
        // Drop anywhere else (at a position that can be related to the expanded
        // tree with the depth of the parent of parentNode). In that case the
        // existing hierarchy is split at the depth of the parent, and will be
        // completed by node's remaining expanded tree.
        const nodeIdToCollapse = expandedParentNodeIds.at(depth + 1);
        return nodeIdToCollapse === undefined
            ? undefined
            : treeExpanded?.nodePerNodeId.get(nodeIdToCollapse);
    }

    validateUpdateParentNode(node, parentNode) {
        if (parentNode.resId === node.resId) {
            this.notification.add(
                _t("The parent record cannot be the record dragged."),
                {
                    type: "danger",
                },
            );
            return false;
        } else if (node.allSubsidiaryResIds.includes(parentNode.resId)) {
            this.notification.add(
                _t("Cannot change the parent because it would create a cycle."),
                {
                    type: "danger",
                },
            );
            return false;
        }
        return true;
    }

    /**
     * Returns a domain to get a recordSet containing:
     * - node.
     * - all children under the new parent.
     * - all descendants in the final expanded tree (after the operation), which
     *   are at a depth impacted by the update @see updateParentNode (part
     *   about the expanded tree).
     *
     * @param {HierarchyNode} node that is moving
     * @param {Number | false} parentResId resId of the parent
     * @param {HierarchyNode} [parentNode] which receives node as its child
     *                        (undefined if node is dropped as a root).
     * @returns {Array} domain
     */
    computeUpdateParentNodeDomain(node, parentResId, parentNode) {
        const domainsOr = [[["id", "=", node.resId]]];
        // Include the new parent children (for ordering).
        domainsOr.push([[this.parentFieldName, "=", parentResId]]);
        let expandedTreeRoot = null;
        if (!node.isLeaf) {
            // Include node descendants (keep that part of the expanded tree).
            expandedTreeRoot = node;
        } else if (!parentNode) {
            // Keep the current expanded tree (if any) from its root if node is a
            // leaf dropped as a root.
            expandedTreeRoot = node.tree.root;
        } else if (!parentNode.isLeaf) {
            // Keep the current expanded tree (if any) from the target parent if
            // node is a leaf.
            expandedTreeRoot = parentNode;
        }
        if (expandedTreeRoot) {
            const expandedTreeParentResIds =
                expandedTreeRoot.descendantsParentNodes.map((n) => n.resId);
            domainsOr.push([[this.parentFieldName, "in", expandedTreeParentResIds]]);
        }
        let domain = Domain.or(domainsOr);
        const globalDomain = this.globalDomain;
        if (globalDomain.length) {
            domain = Domain.and([domain, globalDomain]);
        }
        return domain.toList({});
    }
}
