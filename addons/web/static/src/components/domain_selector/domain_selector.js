// @ts-check
/** @odoo-module native */

import { Component, onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { CheckBox } from "@web/components/checkbox/checkbox";
import { getDomainDisplayedOperators } from "@web/components/domain_selector/domain_selector_operator_editor";
import { ModelFieldSelector } from "@web/components/model_field_selector/model_field_selector";
import { getOperatorEditorInfo, TreeEditor } from "@web/components/tree_editor";
import { Domain } from "@web/core/domain";
import { _t } from "@web/core/translation";
import {
    areEqualTrees,
    condition,
    connector,
    formatValue,
} from "@web/core/tree/condition_tree";
import { domainFromTree } from "@web/core/tree/domain_from_tree";
import { KeepLast, SupersededError } from "@web/core/utils/concurrency";
import { useService } from "@web/core/utils/hooks";

import { getDefaultCondition } from "./utils.js";

const ARCHIVED_CONDITION = condition("active", "in", [true, false]);
const ARCHIVED_DOMAIN = `[("active", "in", [True, False])]`;

export class DomainSelector extends Component {
    static template = "web.DomainSelector";
    static components = { TreeEditor, CheckBox };
    static props = {
        domain: String,
        resModel: String,
        className: { type: String, optional: true },
        defaultConnector: {
            type: [{ value: "&" }, { value: "|" }],
            optional: true,
        },
        isDebugMode: { type: Boolean, optional: true },
        readonly: { type: Boolean, optional: true },
        update: { type: Function, optional: true },
        debugUpdate: { type: Function, optional: true },
    };
    static defaultProps = {
        isDebugMode: false,
        readonly: true,
        update: () => {},
    };

    /** @type {import("services").ServiceFactories["field"]} */
    fieldService;
    /** @type {{ includeArchived: boolean }} */
    state;
    /** @type {import("services").ServiceFactories["tree_processor"]} */
    treeProcessor;

    setup() {
        this.fieldService = useService("field");
        this.treeProcessor = useService("tree_processor");

        this.tree = null;
        this.showArchivedCheckbox = false;
        this.state = useState({ includeArchived: false });
        this.keepLastTree = new KeepLast({ rejectSuperseded: true });

        onWillStart(() => this.onPropsUpdated(this.props));
        onWillUpdateProps((np) => this.onPropsUpdated(np));
    }

    async onPropsUpdated(p) {
        let domain;
        let isSupported = true;
        try {
            domain = new Domain(p.domain);
        } catch {
            isSupported = false;
        }
        if (!isSupported) {
            this.keepLastTree.cancel();
            this.tree = null;
            this.showArchivedCheckbox = false;
            this.state.includeArchived = false;
            return;
        }

        let loaded;
        try {
            loaded = await this.keepLastTree.add(
                Promise.all([
                    this.treeProcessor.treeFromDomain(
                        p.resModel,
                        /** @type {any} */ (domain),
                        !p.isDebugMode,
                    ),
                    this.fieldService.loadFieldInfo(p.resModel, "active"),
                ]),
            );
        } catch (error) {
            if (error instanceof SupersededError) {
                return;
            }
            throw error;
        }
        const [tree, { fieldDef: activeFieldDef }] = loaded;

        this.tree = tree;
        this.showArchivedCheckbox = this.getShowArchivedCheckBox(
            Boolean(activeFieldDef),
            p,
        );

        this.state.includeArchived = false;
        if (this.showArchivedCheckbox) {
            if (this.tree.type === "connector" && this.tree.value === "&") {
                this.tree.children = this.tree.children.filter((child) => {
                    if (areEqualTrees(child, ARCHIVED_CONDITION)) {
                        this.state.includeArchived = true;
                        return false;
                    }
                    return true;
                });
                if (this.tree.children.length === 1) {
                    this.tree = this.tree.children[0];
                }
            } else if (areEqualTrees(this.tree, ARCHIVED_CONDITION)) {
                this.state.includeArchived = true;
                this.tree = connector("&");
            }
        }
    }

    getShowArchivedCheckBox(hasActiveField, props) {
        return hasActiveField;
    }

    getDefaultCondition(fieldDefs) {
        return getDefaultCondition(fieldDefs);
    }

    getDefaultOperator(fieldDef) {
        return getDomainDisplayedOperators(fieldDef)[0];
    }

    getOperatorEditorInfo(fieldDef) {
        const operators = getDomainDisplayedOperators(fieldDef);
        return getOperatorEditorInfo(operators, fieldDef);
    }

    getPathEditorInfo(resModel, defaultCondition) {
        const { isDebugMode } = this.props;
        return {
            component: ModelFieldSelector,
            extractProps: ({ update, value: path }) => ({
                path,
                update,
                resModel,
                isDebugMode,
                readonly: false,
            }),
            isSupported: (path) => [0, 1].includes(path) || typeof path === "string",
            defaultValue: () => defaultCondition.path,
            stringify: (path) => formatValue(path),
            message: _t("Invalid field chain"),
        };
    }

    toggleIncludeArchived() {
        this.state.includeArchived = !this.state.includeArchived;
        this.update(this.tree);
    }

    resetDomain() {
        this.props.update("[]");
    }

    onDomainInput(domain) {
        if (this.props.debugUpdate) {
            this.props.debugUpdate(domain);
        }
    }

    onDomainChange(domain) {
        this.props.update(domain, true);
    }
    update(tree) {
        const archiveDomain = this.state.includeArchived ? ARCHIVED_DOMAIN : `[]`;
        const domain = tree
            ? Domain.and([domainFromTree(tree), archiveDomain]).toString()
            : archiveDomain;
        this.props.update(domain);
    }
}
