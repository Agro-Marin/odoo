// @ts-check
/** @odoo-module native */

/** @module @web/fields/display/statusbar/statusbar_field - Horizontal pipeline status bar for Selection and Many2one columns */

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
import { _t } from "@web/core/l10n/translation";
import { groupBy } from "@web/core/utils/collections/arrays";
import { throttleForAnimation } from "@web/core/utils/timing";
import { registerField } from "@web/fields/_registry";
import { useSpecialData } from "@web/fields/relational/special_data";
import { standardFieldProps } from "@web/fields/standard_field_props";
import { getFieldDomain } from "@web/model/relational_model/utils";
import { useCommand } from "@web/services/commands/command_hook";

/**
 * @typedef {import("@web/fields/standard_field_props").StandardFieldProps & {
 *  domain?: [Array, Function];
 *  foldField?: string;
 *  isDisabled?: boolean;
 *  visibleSelection?: string[];
 *  withCommand?: boolean;
 * }} StatusBarFieldProps
 *
 * @typedef StatusBarItem
 * @property {number} value
 * @property {string} label
 * @property {boolean} isFolded
 * @property {boolean} isSelected
 *
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
    // Upper bound on stages fetched for the many2one variant: a status bar is a
    // pipeline widget, never a full-relation picker.
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
        // Properties
        this.items = {};
        /** @type {StatusBarItem[]} */
        this.allItems = [];
        this.beforeRef = useRef("before");
        this.rootRef = useRef("root");
        this.afterRef = useRef("after");
        this.dropdownRef = useRef("dropdown");

        // Resize listeners
        let status = "idle";
        const adjust = () => {
            status = "adjusting";
            this.adjustVisibleItems();
            this.render();
        };

        useEffect(() => {
            if (status === "shouldAdjust") {
                adjust();
            }
        });

        let forceRecomputeItems = false;
        onWillRender(() => {
            // Cache the item list once per render: it is read by
            // getSortedItems, getCurrentLabel and the template.
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

        // Special data
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
                    // A status bar renders a bounded pipeline of stages; without
                    // a cap a cold form pulls the ENTIRE relation for the handful
                    // of arrows it shows.
                    limit: StatusBarField.RELATION_LIMIT,
                });
                if (value && !res.some((rec) => rec.id === value.id)) {
                    // The cap (and, when no narrowing domain is set, the
                    // relation's default order) can push the currently-selected
                    // record past the fetched window. OR-ing it into `domain`
                    // above only guarantees it *matches*, not that it lands
                    // within the limit, so fetch it explicitly and append it;
                    // otherwise getAllItems() yields no isSelected item and the
                    // bar falls back to the "More" label with nothing highlighted.
                    const current = await orm.read(relation, [value.id], fieldNames, {
                        context,
                    });
                    res.push(...current);
                }
                forceRecomputeItems = true;
                return res;
            });
        }

        // Command palette
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

    /**
     * Override this to force a dynamic domain on the records
     */
    getDomain(props) {
        return [];
    }

    /**
     * Override this to change the fields to fetch
     */
    getFieldNames(props) {
        return ["display_name"];
    }

    /**
     * Determines what items are visible and how they're displayed. Adjusts
     * incrementally as space runs out: (1) all items inline; (2) items before
     * the selected one collapse into a leading dropdown; (3) items after it
     * (plus initially folded ones) also collapse; (4) last resort: single dropdown.
     */
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

        // Reset hidden elements
        show(...itemEls);
        hide(this.dropdownRef.el, this.beforeRef.el);
        if (this.items.folded.length) {
            show(this.afterRef.el);
            itemEls.forEach((el) => el.classList.remove("o_first"));
        } else {
            hide(this.afterRef.el);
            itemEls[0]?.classList.add("o_first");
        }

        // Reset items variables
        this.items.before = [];
        this.items.after = [...this.items.folded];
        const itemsToAssign = this.allItems.filter((item) => !item.isFolded);

        if (this.env.isSmall && this.items.inline.length) {
            // Small screen case: only a single dropdown
            show(this.dropdownRef.el);
            hide(this.beforeRef.el, this.afterRef.el, ...itemEls);
            return;
        }

        while (this.areItemsWrapping()) {
            if (itemsBefore.length) {
                // Case 1: elements before can be hidden
                show(this.beforeRef.el);
                hide(itemsBefore.shift());
                this.items.before.push(itemsToAssign.shift());
            } else if (itemsAfter.length) {
                // Case 2: elements before are hidden, elements after can be hidden
                show(this.afterRef.el);
                hide(itemsAfter.pop());
                this.items.after.unshift(itemsToAssign.pop());
            } else {
                // Last resort: no elements can be hidden => fallback to single dropdown
                show(this.dropdownRef.el);
                hide(this.beforeRef.el, this.afterRef.el, ...itemEls);
                break;
            }
        }
    }

    areItemsWrapping() {
        const root = this.rootRef.el;
        const firstItem = root.querySelector(":scope > :not(.d-none)");
        if (!firstItem) {
            return false;
        }
        const { height: currentHeight } = root.getBoundingClientRect();
        const { height: targetHeight } = firstItem.getBoundingClientRect();
        return currentHeight > targetHeight;
    }

    /**
     * @returns {StatusBarItem[]}
     */
    getAllItems() {
        const { foldField, name, record } = this.props;
        const currentValue = record.data[name];
        if (this.field.type === "many2one") {
            // Many2one
            return this.specialData.data.map((option) => ({
                value: option.id,
                label: option.display_name,
                isFolded: option[foldField],
                isSelected: Boolean(currentValue && option.id === currentValue.id),
            }));
        } else {
            // Selection
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
        inline.reverse(); // CSS rules account for this list to be reversed
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

export const statusBarField = {
    component: StatusBarField,
    displayName: _t("Status"),
    supportedOptions: [
        {
            label: _t("Clickable"),
            name: "clickable",
            type: "boolean",
            default: true,
        },
        {
            label: _t("Fold field"),
            name: "fold_field",
            type: "field",
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
        // An empty attribute must mean "no restriction", not `[""]` (which
        // would filter the selection down to the current value only).
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
