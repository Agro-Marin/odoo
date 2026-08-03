// @ts-check
/** @odoo-module native */

/** @module @web/fields/relational/many2one/many2one */

import { Component, toRaw, useRef, useState } from "@odoo/owl";
import { BarcodeScanner } from "@web/components/barcode/barcode_dialog";
import { isBarcodeScannerSupported } from "@web/components/barcode/barcode_video_scanner";
import { useAction } from "@web/core/action_port";
import { isMobileOS } from "@web/core/browser/feature_detection";
import { makeContext } from "@web/core/context";
import { evaluateBooleanExpr } from "@web/core/py_js/py";
import { _t } from "@web/core/translation";
import { useService } from "@web/core/utils/hooks";
import { getFieldDomain } from "@web/model/relational_model/utils";
import { usePopover } from "@web/ui/popover/popover_hook";

import { Many2XAutocomplete, useOpenMany2XRecord } from "../many2x_autocomplete.js";

/**
 * @param {Object} record
 * @returns {{ id: number, display_name: string }}
 */
export function extractData(record) {
    let name;
    if ("display_name" in record) {
        name = record.display_name;
    } else if ("name" in record) {
        name = record.name?.id ? record.name.display_name : record.name;
    }
    return { id: record.id, display_name: name };
}

/**
 * @param {Object} fieldProps
 * @returns {Object}
 */
export function computeM2OProps(fieldProps) {
    const computeLinkCssClass = () => {
        if (!fieldProps.decorations) {
            return "";
        }
        const evalContext = fieldProps.record.evalContextWithVirtualIds;
        for (const decorationName of Object.keys(fieldProps.decorations)) {
            if (
                evaluateBooleanExpr(fieldProps.decorations[decorationName], evalContext)
            ) {
                return `text-${decorationName}`;
            }
        }
        return "";
    };

    return {
        canCreate: fieldProps.canCreate,
        canCreateEdit: fieldProps.canCreateEdit,
        canOpen: fieldProps.canOpen,
        canQuickCreate: fieldProps.canQuickCreate,
        canScanBarcode: fieldProps.canScanBarcode,
        canWrite: fieldProps.canWrite,
        context: fieldProps.context,
        domain: () =>
            getFieldDomain(fieldProps.record, fieldProps.name, fieldProps.domain),
        id: fieldProps.id,
        linkCssClass: computeLinkCssClass(),
        nameCreateField: fieldProps.nameCreateField,
        openActionContext: () => {
            const { context, name, openActionContext, record } = fieldProps;
            return makeContext(
                [openActionContext || context, record.fields[name].context],
                record.evalContext,
            );
        },
        placeholder: fieldProps.placeholder,
        readonly: fieldProps.readonly,
        relation: fieldProps.record.fields[fieldProps.name].relation,
        searchMemoization: fieldProps.searchMemoization,
        searchThreshold: fieldProps.searchThreshold,
        string:
            fieldProps.string || fieldProps.record.fields[fieldProps.name].string || "",
        update: (value, options = {}) =>
            fieldProps.record.update({ [fieldProps.name]: value }, options),
        value: toRaw(fieldProps.record.data[fieldProps.name]),
    };
}

export class Many2One extends Component {
    static template = "web.Many2One";
    static components = { Many2XAutocomplete };

    /**
     * @type {ReturnType<typeof import("@web/core/name_service").nameService.start>}
     */
    nameService;
    static props = {
        canCreate: { type: Boolean, optional: true },
        canCreateEdit: { type: Boolean, optional: true },
        canOpen: { type: Boolean, optional: true },
        canQuickCreate: { type: Boolean, optional: true },
        canScanBarcode: { type: Boolean, optional: true },
        canWrite: { type: Boolean, optional: true },
        context: { type: Object, optional: true },
        createAction: { type: Function, optional: true },
        cssClass: { type: String, optional: true },
        domain: { type: Function, optional: true },
        id: { type: String, optional: true },
        linkCssClass: { type: String, optional: true },
        nameCreateField: { type: String, optional: true },
        openActionContext: { type: Function, optional: true },
        openRecordAction: { type: Function, optional: true },
        otherSources: { type: Array, optional: true },
        placeholder: { type: String, optional: true },
        readonly: { type: Boolean, optional: true },
        relation: { type: String },
        searchMoreLabel: { type: String, optional: true },
        searchThreshold: { type: Number, optional: true },
        searchMemoization: { type: String, optional: true },
        slots: { type: Object, optional: true },
        specification: { type: Object, optional: true },
        string: { type: String, optional: true },
        update: { type: Function },
        value: { type: [Array, Object, { value: false }], optional: true },
    };
    static defaultProps = {
        canCreate: true,
        canCreateEdit: true,
        canOpen: true,
        canQuickCreate: true,
        canScanBarcode: false,
        canWrite: true,
        context: {},
        domain: () => [],
        linkCssClass: "",
        nameCreateField: "name",
        otherSources: [],
        placeholder: "",
        readonly: false,
        string: "",
    };

    /** @type {import("@odoo/owl").Ref<HTMLElement>} */
    rootRef;
    /** @type {import("@web/core/action_port").ActionPort} */
    action;
    /** @type {import("services").ServiceFactories["notification"]} */
    notification;
    /** @type {import("services").ServiceFactories["orm"]} */
    orm;
    /** @type {{ isFloating: boolean }} */
    state;
    /** @type {any} */
    recordDialog;

    setup() {
        this.rootRef = useRef("root");

        this.action = useAction();
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.nameService = useService("name");

        this.state = useState({ isFloating: false });

        const self = this;
        this.recordDialog = {
            open: useOpenMany2XRecord({
                activeActions: {
                    get create() {
                        return self.props.canCreate;
                    },
                    get createEdit() {
                        return self.props.canCreateEdit;
                    },
                    get write() {
                        return self.props.canWrite;
                    },
                },
                fieldString: this.props.string,
                isToMany: false,
                onClose: () => {
                    this.input?.focus();
                },
                onRecordSaved: async () => {
                    const resId = this.props.value?.id;
                    if (resId == null) {
                        return;
                    }
                    const fieldNames = ["display_name"];
                    const records = await this.orm.read(
                        this.props.relation,
                        [resId],
                        fieldNames,
                        {
                            context: this.props.context,
                        },
                    );
                    if (records[0]) {
                        this.nameService.addDisplayNames(this.props.relation, {
                            [resId]: records[0].display_name,
                        });
                    }
                    await this.update(records[0] ? extractData(records[0]) : false);
                },
                onRecordDiscarded: () => {},
                resModel: this.props.relation,
            }),
        };
    }

    /** @returns {{ create: boolean, createEdit: boolean, write: boolean }} */
    get activeActions() {
        return {
            create: this.props.canCreate,
            createEdit: this.props.canCreateEdit,
            write: this.props.canWrite,
        };
    }

    /** @returns {Object} */
    get many2XAutocompleteProps() {
        return {
            activeActions: this.activeActions,
            autoSelect: true,
            context: this.props.context,
            createAction: this.props.createAction,
            fieldString: this.props.string,
            getDomain: this.props.domain,
            id: this.props.id,
            nameCreateField: this.props.nameCreateField,
            otherSources: this.props.otherSources,
            placeholder: this.props.placeholder,
            quickCreate: this.props.canQuickCreate
                ? (name) => this.quickCreate(name)
                : null,
            resModel: this.props.relation,
            searchMoreLabel: this.props.searchMoreLabel,
            searchThreshold: this.props.searchThreshold,
            searchMemoization: this.props.searchMemoization,
            setInputFloats: (isFloating) => {
                this.state.isFloating = isFloating;
            },
            slots: this.props.slots,
            specification: this.props.specification,
            update: (records) => {
                const idNamePair =
                    records && records[0] ? extractData(records[0]) : false;
                return this.update(idNamePair);
            },
            value: this.displayName,
        };
    }

    /** @returns {string} */
    get displayName() {
        if (this.props.value) {
            if (this.props.value.display_name) {
                return this.props.value.display_name.split("\n")[0];
            } else {
                return _t("Unnamed");
            }
        } else {
            return "";
        }
    }

    /** @returns {string[]} */
    get extraLines() {
        const name = this.props.value?.display_name;
        return name
            ? name
                  .split("\n")
                  .map((line) => line.trim())
                  .slice(1)
            : [];
    }

    /** @returns {boolean} */
    get hasBarcodeButton() {
        const supported = isBarcodeScannerSupported();
        return (
            this.props.canScanBarcode &&
            isMobileOS() &&
            supported &&
            !this.hasLinkButton
        );
    }

    /** @returns {boolean} */
    get hasLinkButton() {
        return (
            this.props.canOpen &&
            typeof this.props.value?.id === "number" &&
            !this.state.isFloating
        );
    }

    /** @returns {HTMLInputElement|null} */
    get input() {
        return this.rootRef.el?.querySelector("input") ?? null;
    }

    /** @returns {string} */
    get linkHref() {
        if (!this.props.value) {
            return "/";
        }
        const relation = this.props.relation.includes(".")
            ? this.props.relation
            : `m-${this.props.relation}`;
        return `/odoo/${relation}/${this.props.value.id}`;
    }

    async openBarcodeScanner() {
        const barcode = await BarcodeScanner.scanBarcode(this.env);
        if (barcode) {
            await this.processScannedBarcode(barcode);
            if ("vibrate" in navigator) {
                navigator.vibrate(100);
            }
        } else {
            /** @type {any} */
            const message = _t("Please, scan again!");
            this.notification.add(message, { type: "warning" });
        }
    }

    /** @param {"action"|"dialog"|"tab"} mode */
    async openRecord(mode) {
        if (this.props.openRecordAction) {
            return this.props.openRecordAction(mode);
        }

        switch (mode) {
            case "action": {
                return this.openRecordInAction(false);
            }
            case "dialog": {
                return this.openRecordInDialog();
            }
            case "tab": {
                return this.openRecordInAction(true);
            }
        }
    }

    /** @param {boolean} newWindow */
    async openRecordInAction(newWindow) {
        const action = await this.orm.call(
            this.props.relation,
            "get_formview_action",
            [[this.props.value?.id]],
            { context: this.props.openActionContext() },
        );
        await this.action.doAction(action, { newWindow });
    }

    async openRecordInDialog() {
        return this.recordDialog.open({
            resId: this.props.value?.id,
            context: this.props.context,
        });
    }

    /** @param {string} barcode */
    async processScannedBarcode(barcode) {
        const pairs = await this.orm.call(this.props.relation, "name_search", [], {
            name: barcode,
            domain: this.props.domain(),
            operator: "ilike",
            limit: 2,
            context: this.props.context,
        });
        const validPairs = pairs.filter(([id]) => !!id);
        if (validPairs.length === 1) {
            const pair = validPairs[0];
            return this.update({ id: pair[0], display_name: pair[1] });
        } else {
            const input = this.input;
            if (!input) {
                return;
            }
            input.value = barcode;
            input.dispatchEvent(new Event("input"));
            if (this.env.isSmall) {
                input.dispatchEvent(new Event("barcode-search"));
            }
        }
    }

    /**
     * @param {string} name
     * @returns {Promise}
     */
    quickCreate(name) {
        return this.update({ id: false, display_name: name });
    }

    /**
     * @param {{ id: number|false, display_name: string }|false} idNamePair
     * @returns {Promise}
     */
    update(idNamePair) {
        this.state.isFloating = false;
        return this.props.update(idNamePair);
    }
}

class KanbanMany2OneAssignPopover extends Many2One {
    static props = {
        ...super.props,
        close: Function,
    };

    get many2XAutocompleteProps() {
        return {
            ...super.many2XAutocompleteProps,
            dropdown: false,
        };
    }
}

export class KanbanMany2One extends Component {
    static template = "web.KanbanMany2One";
    static props = { ...Many2One.props };

    /** @type {any} */
    assignPopover;

    setup() {
        this.assignPopover = usePopover(KanbanMany2OneAssignPopover, {
            popoverClass: "o_m2o_tags_avatar_field_popover",
        });
    }

    /** @param {HTMLElement} target */
    openAssignPopover(target) {
        this.assignPopover.open(target, {
            ...this.props,
            canCreate: false,
            canCreateEdit: false,
            canQuickCreate: false,
            placeholder: this.props.placeholder || _t("Search user..."),
            readonly: false,
            update: async (value) => {
                await this.props.update(value, { save: true });
                this.assignPopover.close();
            },
        });
    }
}
