// @ts-check
/** @odoo-module native */

/** @module @web/fields/display/statusbar/statusbar_field */

import {
    Component,
    onWillRender,
    onWillUnmount,
    useEffect,
    useExternalListener,
    useRef,
} from "@odoo/owl";
import { Dropdown } from "@web/components/dropdown/dropdown";
import { DropdownItem } from "@web/components/dropdown/dropdown_item";
import { Domain } from "@web/core/domain";
import { _t } from "@web/core/translation";
import { groupBy } from "@web/core/utils/collections/arrays";
import { throttleForAnimation } from "@web/core/utils/timing";
import { registerField } from "@web/fields/_registry";
import { useSpecialData } from "@web/fields/relational/special_data";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { getFieldDomain } from "@web/model/relational_model/utils";
import { useCommand } from "@web/ui/commands/command_hook";

/**
 * @typedef {import("@web/fields/standard_field_props").StandardFieldProps & {
 *  domain?: [Array, Function];
 *  foldField?: string;
 *  isDisabled?: boolean;
 *  visibleSelection?: string[];
 *  withCommand?: boolean;
 * }} StatusBarFieldProps
 * @typedef StatusBarItem
 * @property {number} value
 * @property {string} label
 * @property {boolean} isFolded
 * @property {boolean} isSelected
 * @typedef StatusBarList
 * @property {string} label
 * @property {StatusBarItem[]} items
 */

/**
 * @param {...HTMLElement} els
 */
const hide = (...els) => els.forEach((el) => el.classList.add("d-none"));

/**
 * @param {...HTMLElement} els
 */
const show = (...els) => els.forEach((el) => el.classList.remove("d-none"));

/** @extends {Component<StatusBarFieldProps>} */
export class StatusBarField extends Component {
    static template = "web.StatusBarField";
    static RELATION_LIMIT = 100;
    static components = {
        Dropdown,
        DropdownItem,
    };
    static props = {
        ...standardFieldProps,
        domain: { type: [Array, Function], optional: true },
        foldField: { type: String, optional: true },
        isDisabled: { type: Boolean, optional: true },
        visibleSelection: { type: Array, element: String, optional: true },
        withCommand: { type: Boolean, optional: true },
        context: { type: Object, optional: true },
    };

    setup() {
        this.items = {};
        /** @type {StatusBarItem[]} */
        this.allItems = [];
        this.beforeRef = useRef("before");
        this.rootRef = useRef("root");
        this.afterRef = useRef("after");
        this.dropdownRef = useRef("dropdown");

        let status = "idle";
        const adjust = () => {
            status = "adjusting";
            this.adjustVisibleItems();
            this.render();
        };

        // What the visible window actually depends on: the items themselves and
        // the room available for them. Every render used to schedule a full
        // adjust pass, so editing an unrelated field elsewhere on the form paid
        // one -- and a pass hides items one at a time, forcing a layout per
        // step. Re-check both cheaply and skip the pass when neither moved.
        let lastSignature = null;
        let lastWidth = null;
        useEffect(() => {
            if (status !== "shouldAdjust") {
                return;
            }
            const signature = JSON.stringify(this.allItems);
            const width = this.rootRef.el?.getBoundingClientRect().width ?? null;
            if (signature === lastSignature && width === lastWidth) {
                status = "idle";
                return;
            }
            lastSignature = signature;
            lastWidth = width;
            adjust();
        });

        let forceRecomputeItems = false;
        onWillRender(() => {
            this.allItems = this.getAllItems();
            if (status !== "adjusting" || forceRecomputeItems) {
                Object.assign(this.items, this.getSortedItems());
                status = "shouldAdjust";
            } else {
                status = "idle";
            }
            forceRecomputeItems = false;
        });

        this.throttledAdjust = throttleForAnimation(adjust);
        useExternalListener(window, "resize", this.throttledAdjust);
        onWillUnmount(() => this.throttledAdjust.cancel());

        if (this.field.type === "many2one") {
            this.specialData = useSpecialData(async (orm, props) => {
                const { foldField, name: fieldName, record, context } = props;
                const { relation } = record.fields[fieldName];
                const fieldNames = this.getFieldNames(props);
                if (foldField) {
                    fieldNames.push(foldField);
                }
                const value = record.data[fieldName];
                let domain = getFieldDomain(record, fieldName, props.domain);
                domain = Domain.and([this.getDomain(props), domain]).toList();
                if (domain.length && value) {
                    domain = Domain.or([[["id", "=", value.id]], domain]).toList(
                        record.evalContext,
                    );
                }
                const res = await orm.searchRead(relation, domain, fieldNames, {
                    context,
                    limit: /** @type {any} */ (this.constructor).RELATION_LIMIT,
                });
                forceRecomputeItems = true;
                return res;
            });
        }

        if (this.props.withCommand) {
            const moveToCommandName = _t("Move to %s...", this.field.string);
            useCommand(
                moveToCommandName,
                () => ({
                    placeholder: moveToCommandName,
                    providers: [
                        {
                            provide: () =>
                                /** @type {any} */ (
                                    this.getAllItems().map((item) => ({
                                        name: item.label,
                                        action: () => this.selectItem(item),
                                    }))
                                ),
                        },
                    ],
                }),
                {
                    category: "smart_action",
                    hotkey: "alt+shift+x",
                    isAvailable: () => !this.props.isDisabled,
                },
            );
            useCommand(
                _t("Move to next %s", this.field.string),
                () => {
                    const items = this.getAllItems();
                    const nextIndex = items.findIndex((item) => item.isSelected) + 1;
                    this.selectItem(items[nextIndex]);
                },
                {
                    category: "smart_action",
                    hotkey: "alt+x",
                    isAvailable: () => {
                        if (this.props.isDisabled) {
                            return false;
                        }
                        const items = this.getAllItems();
                        return items.length && !items.at(-1).isSelected;
                    },
                },
            );
        }
    }

    /**
     * @returns {{ selection?: [string, string][], string: string, type: "many2one" | "selection" }}
     */
    get field() {
        return /** @type {any} */ (this.props.record.fields[this.props.name]);
    }

    getDomain(props) {
        return [];
    }

    getFieldNames(props) {
        return ["display_name"];
    }

    adjustVisibleItems() {
        const itemEls = [
            ...this.rootRef.el.querySelectorAll(
                ".o_arrow_button:not(.dropdown-toggle)",
            ),
        ];
        const selectedIndex = itemEls.findIndex((el) =>
            el.classList.contains("o_arrow_button_current"),
        );
        const itemsBefore = itemEls.slice(selectedIndex + 2).reverse();
        const itemsAfter = itemEls.slice(0, Math.max(selectedIndex - 1, 0)).reverse();

        show(...itemEls);
        hide(this.dropdownRef.el, this.beforeRef.el);
        if (this.items.folded.length) {
            show(this.afterRef.el);
            itemEls.forEach((el) => el.classList.remove("o_first"));
        } else {
            hide(this.afterRef.el);
            itemEls[0]?.classList.add("o_first");
        }

        this.items.before = [];
        this.items.after = [...this.items.folded];
        const itemsToAssign = this.allItems.filter((item) => !item.isFolded);

        if (this.env.isSmall && this.items.inline.length) {
            show(this.dropdownRef.el);
            hide(this.beforeRef.el, this.afterRef.el, ...itemEls);
            return;
        }

        // Every item hidden below costs a forced synchronous layout, and the
        // loop used to pay two of them per step: one for the root, one to
        // re-derive the height of a single row. The children all sit in the
        // same wrapping flex row, so that second measurement is invariant for
        // the whole pass -- take it once.
        this._rowHeight = null;
        try {
            while (this.areItemsWrapping()) {
                if (itemsBefore.length) {
                    show(this.beforeRef.el);
                    hide(itemsBefore.shift());
                    this.items.before.push(itemsToAssign.shift());
                } else if (itemsAfter.length) {
                    show(this.afterRef.el);
                    hide(itemsAfter.pop());
                    this.items.after.unshift(itemsToAssign.pop());
                } else {
                    show(this.dropdownRef.el);
                    hide(this.beforeRef.el, this.afterRef.el, ...itemEls);
                    break;
                }
            }
        } finally {
            this._rowHeight = null;
        }
    }

    areItemsWrapping() {
        const root = this.rootRef.el;
        if (this._rowHeight === null) {
            const firstItem = root.querySelector(":scope > :not(.d-none)");
            if (!firstItem) {
                return false;
            }
            this._rowHeight = firstItem.getBoundingClientRect().height;
        }
        return root.getBoundingClientRect().height > this._rowHeight;
    }

    /**
     * @returns {StatusBarItem[]}
     */
    getAllItems() {
        const { foldField, name, record } = this.props;
        const currentValue = record.data[name];
        if (this.field.type === "many2one") {
            return this.specialData.data.map((option) => ({
                value: option.id,
                label: option.display_name,
                isFolded: option[foldField],
                isSelected: Boolean(currentValue && option.id === currentValue.id),
            }));
        } else {
            let { selection } = this.field;
            const { visibleSelection } = this.props;
            if (visibleSelection?.length) {
                selection = selection.filter(
                    ([value]) =>
                        value === currentValue || visibleSelection.includes(value),
                );
            }
            return /** @type {any} */ (
                selection.map(([value, label]) => ({
                    value,
                    label,
                    isFolded: false,
                    isSelected: value === currentValue,
                }))
            );
        }
    }

    getCurrentLabel() {
        return this.allItems.find((item) => item.isSelected)?.label || _t("More");
    }

    /**
     * @param {StatusBarItem} item
     */
    getDropdownItemClassNames(item) {
        const classNames = [];
        if (item.isSelected) {
            classNames.push("active");
        }
        if (item.isSelected || this.props.isDisabled) {
            classNames.push("disabled");
        }
        return classNames.join(" ");
    }

    getSortedItems() {
        const before = [];
        const after = [];
        const { true: inline = [], false: folded = [] } = /** @type {any} */ (
            groupBy(
                this.allItems,
                /** @type {any} */ ((item) => item.isSelected || !item.isFolded),
            )
        );
        inline.reverse();
        after.push(...folded);
        return { inline, before, after, folded };
    }

    /**
     * @param {StatusBarItem} item
     */
    async selectItem(item) {
        const { name, record } = this.props;
        const value =
            this.field.type === "many2one"
                ? { id: item.value, display_name: item.label }
                : item.value;
        await record.update({ [name]: value });
        await record.save();
    }

    /**
     * @param {CustomEvent<{ payload: StatusBarItem }>} ev
     */
    onDropdownItemSelected(ev) {
        this.selectItem(ev.detail.payload);
    }
}

/** @type {import("registries").FieldsRegistryItemShape} */
export const statusBarField = {
    component: StatusBarField,
    displayName: _t("Status"),
    supportedOptions: [
        {
            label: _t("Clickable"),
            name: "clickable",
            type: "boolean",
            default: false,
        },
        {
            label: _t("Fold field"),
            name: "fold_field",
            type: "field",
            isRelationalField: true,
            availableTypes: ["boolean"],
            help: _t(
                "Boolean field from the model used in the relation, which indicates whether the state is folded or not.",
            ),
        },
    ],
    supportedTypes: ["many2one", "selection"],
    isEmpty: (record, fieldName) => !record.data[fieldName],
    extractProps: ({ attrs, options, viewType }, dynamicInfo) => ({
        isDisabled: !options.clickable || dynamicInfo.readonly,
        visibleSelection: attrs.statusbar_visible?.trim()
            ? attrs.statusbar_visible.trim().split(/\s*,\s*/g)
            : undefined,
        withCommand: viewType === "form",
        foldField: options.fold_field,
        domain: dynamicInfo.domain,
        context: dynamicInfo.context,
    }),
};

registerField("statusbar", statusBarField);
