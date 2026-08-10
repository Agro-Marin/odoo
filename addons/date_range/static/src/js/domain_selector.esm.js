/** @odoo-module native */
import {onWillStart, useChildSubEnv} from "@odoo/owl";
import {DomainSelector} from "@web/components/domain_selector/domain_selector";
import {patch} from "@web/core/utils/patch";
import {useService} from "@web/core/utils/hooks";
import {_t} from "@web/core/translation";

/**
 * Patch DomainSelector to add date range support.
 *
 * Deliberately narrow: only `setup` and `getOperatorEditorInfo` are touched.
 * `onPropsUpdated` used to be overridden here with a copy of an older core
 * implementation that contained no date-range logic at all. Being a copy, it
 * drifted: it wrote `this.includeArchived` where core reads
 * `this.state.includeArchived`, and compared the archived condition with
 * `JSON.stringify` against a hand-written literal that core's `condition()`
 * factory no longer produces (it gained an `isProperty` key), so the "include
 * archived" checkbox never recognised a domain that already had the condition.
 * The daterange transformations run through the virtual-operator pipeline, so
 * no override is needed.
 */
patch(DomainSelector.prototype, {
    /**
     * Setup the component and load date ranges from backend.
     * Extends the parent setup to:
     * - Initialize date_range service
     * - Load date ranges and types (cached)
     * - Provide domain context to child components
     * - Add error notifications
     */
    setup() {
        super.setup(...arguments);

        // Initialize services
        this.dateRangeService = useService("date_range");
        this.notification = useService("notification");

        // Initialize date range data
        this.dateRanges = [];
        this.dateRangeTypes = [];

        // Provide domain context to child components (TreeEditor)
        // This allows TreeEditor to access dateRanges for value selection
        useChildSubEnv({domain: this});

        // Load date ranges before component renders (using cached service)
        onWillStart(async () => {
            try {
                // Load from cached service (single API call shared across instances)
                const {ranges, types} = await this.dateRangeService.loadDateRanges();
                this.dateRanges = ranges;
                this.dateRangeTypes = types;
            } catch {
                // The domain editor stays usable without periods: the operator
                // simply is not offered. The notification below is the report;
                // a console.error alongside it was both duplicate and an
                // eslint no-undef error, `console` not being a declared global.
                this.dateRanges = [];
                this.dateRangeTypes = [];

                // Notify user about the issue
                this.notification.add(
                    _t(
                        "Date ranges could not be loaded. Date range filters will not be available."
                    ),
                    {
                        type: "warning",
                        sticky: false,
                    }
                );
            }
        });
    },

    /**
     * Get operator editor information for a field, with date range operators injected.
     * This method is called by TreeEditor to determine which operators are available
     * for a field and how to display them.
     *
     * For date/datetime fields, this adds:
     * - "daterange" operator (generic date range selector)
     * - "daterange_X" operators (typed date ranges like quarterly, monthly)
     *
     * @param {Object} fieldDef - Field definition from model
     * @param {string} fieldDef.type - Field type (e.g., "date", "datetime", "char")
     * @returns {Object} Operator editor configuration with date range operators added
     */
    getOperatorEditorInfo(fieldDef) {
        // Get standard operator info from parent
        const info = super.getOperatorEditorInfo(fieldDef);

        // Cache date ranges for closure
        const dateRanges = this.dateRanges;
        const dateRangeTypes = this.dateRangeTypes.filter((dt) => dt.date_ranges_exist);

        // Wrap extractProps to inject date range operators
        const originalExtractProps = info.extractProps;
        info.extractProps = (args) => {
            const props = originalExtractProps.call(info, args);
            const [operator] = args.value;

            // Check if this field supports date ranges
            const isDateField =
                fieldDef && (fieldDef.type === "date" || fieldDef.type === "datetime");
            const hasDateRanges = isDateField && dateRanges.length > 0;
            const hasDateRangeTypes = isDateField && dateRangeTypes.length > 0;

            if (hasDateRanges) {
                // Keep the selected daterange operator selected
                if (operator === "daterange") {
                    props.value = "daterange";
                }

                // Add generic daterange operator
                if (!props.options.some(([op]) => op === "daterange")) {
                    props.options.push(["daterange", _t("in date range")]);
                }
            }

            if (hasDateRangeTypes) {
                // Check if current operator is a typed daterange (e.g., "daterange_1")
                const selectedDateRange = dateRangeTypes.find(
                    (rangeType) =>
                        typeof operator === "string" &&
                        rangeType.id === Number(operator.split("daterange_")[1])
                );

                // Preserve typed daterange selection
                if (selectedDateRange) {
                    props.value = operator;
                }

                // Add all typed daterange operators
                for (const rangeType of dateRangeTypes) {
                    const operatorKey = `daterange_${rangeType.id}`;
                    if (!props.options.some(([op]) => op === operatorKey)) {
                        props.options.push([operatorKey, _t("in %s", rangeType.name)]);
                    }
                }
            }

            return props;
        };

        return info;
    },

    // Note: We don't override update() - the parent's implementation uses domainFromTree()
    // which automatically calls eliminateVirtualOperators() (patched to handle date range
    // operators). The archived domain handling is also done by parent.
});
