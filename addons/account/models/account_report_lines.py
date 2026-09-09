import datetime
import json
import re
from collections import defaultdict
from functools import cmp_to_key

from odoo import _, api, models
from odoo.exceptions import UserError

from .account_report_engine import (
    LINE_ID_HIERARCHY_DELIMITER,
    NUMBER_FIGURE_TYPES,
)


class AccountReportLines(models.Model):
    _inherit = "account.report"

    def _prepare_columns_from_column_group_vals(
        self, options, all_column_group_vals_in_order
    ):
        def _generate_domain_from_horizontal_group_hash_key_tuple(group_hash_key):
            domain = []
            for field_name, field_value in group_hash_key:
                domain.append((field_name, "=", field_value))
            return domain

        columns = []
        column_groups = {}
        for column_group_val in all_column_group_vals_in_order:
            horizontal_group_key_tuple = self._get_dict_hashable_key_tuple(
                column_group_val["horizontal_groupby_element"]
            )  # Empty tuple if no grouping
            column_group_key = str(
                self._get_dict_hashable_key_tuple(column_group_val)
            )  # Unique identifier for the column group

            column_groups[column_group_key] = {
                "forced_options": column_group_val["forced_options"],
                "forced_domain": _generate_domain_from_horizontal_group_hash_key_tuple(
                    horizontal_group_key_tuple
                ),
            }
            if horizontal_group_key_tuple:
                column_groups[column_group_key]["horizontal_groupby_element"] = (
                    horizontal_group_key_tuple
                )

            # for budget, only one column in needed, regardless of the number of columns in the report
            if any(
                budget_key in column_group_val["forced_options"]
                for budget_key in ("compute_budget", "budget_percentage")
            ):
                columns.append(
                    {
                        "name": "",
                        "column_group_key": column_group_key,
                        "expression_label": "balance",
                        "sortable": False,
                        "figure_type": "monetary",
                        "blank_if_zero": False,
                        "class": "text-nowrap text-end",
                    }
                )

            else:
                for report_column in self.column_ids:
                    columns.append(  # noqa: PERF401
                        {
                            "name": report_column.name,
                            "column_group_key": column_group_key,
                            "expression_label": report_column.expression_label,
                            "sortable": report_column.sortable,
                            "figure_type": report_column.figure_type,
                            "blank_if_zero": report_column.blank_if_zero,
                            "class": f"text-nowrap {'text-end' if report_column.figure_type in NUMBER_FIGURE_TYPES else 'text-center'}",
                        }
                    )

        return columns, column_groups

    @api.model
    def _get_line_from_xml_id(self, lines, xml_id):
        """Helper function to get a specific account report line from the xmlid"""
        report_line = self.env.ref(xml_id, raise_if_not_found=False)
        return next(
            line
            for line in lines
            if self._get_model_info_from_id(line["id"])
            == ("account.report.line", report_line.id)
        )

    @api.model
    def _prepare_line_id(self, current):
        """Build a generic line id string from its list representation, converting
        the None values for model and value to empty strings.
        :param current (list<tuple>): list of tuple(markup, model, value)
        """

        def convert_none(x):
            return x if x is not None and x is not False else ""

        def check_segment(part):
            # The format escapes nothing, so a markup or a non-relational groupby
            # value carrying either delimiter builds an id that cannot be parsed
            # back. Fail here, where the offending value is still in hand, rather
            # than somewhere downstream with an id nobody can trace. The format
            # itself is not changed: account.report.annotation persists these ids.
            if "~" in part or LINE_ID_HIERARCHY_DELIMITER in part:
                raise UserError(
                    _(
                        "A report line id segment cannot contain %(tilde)s or %(delimiter)s: %(segment)s",
                        tilde="~",
                        delimiter=LINE_ID_HIERARCHY_DELIMITER,
                        segment=part,
                    )
                )
            return part

        return LINE_ID_HIERARCHY_DELIMITER.join(
            "~".join(
                check_segment(str(convert_none(part)))
                for part in (markup, model, value)
            )
            for markup, model, value in current
        )

    def _get_lines(
        self, options, all_column_groups_expression_totals=None, warnings=None
    ):
        self.check_singleton()

        if options["report_id"] != self.id:
            # Should never happen; just there to prevent BIG issues and directly spot them
            raise UserError(
                _(
                    "Inconsistent report_id in options dictionary. Options says %(options_report)s; report is %(report)s.",
                    options_report=options["report_id"],
                    report=self.id,
                )
            )

        # Necessary to ensure consistency of the data if some of them haven't been written in database yet
        self.env.flush_all()

        if warnings is not None:
            self._generate_common_warnings(options, warnings)

        # Merge static and dynamic lines in a common list
        if all_column_groups_expression_totals is None:
            self._init_currency_table(options)
            all_column_groups_expression_totals = (
                self._compute_expression_totals_for_each_column_group(
                    self.line_ids.expression_ids,
                    options,
                    warnings=warnings,
                )
            )

        dynamic_lines = self._get_dynamic_lines(
            options, all_column_groups_expression_totals, warnings=warnings
        )

        lines = []
        line_cache = {}  # {report_line: report line dict}
        hide_if_zero_lines = self.env["account.report.line"]

        # There are two types of lines:
        # - static lines: the ones generated from self.line_ids
        # - dynamic lines: the ones generated from a call to the functions referred to by self.dynamic_lines_generator
        # This loops combines both types of lines together within the lines list
        for line in self.line_ids:  # _order ensures the sequence of the lines
            # Inject all the dynamic lines whose sequence is inferior to the next static line to add
            while dynamic_lines and line.sequence > dynamic_lines[0][0]:
                lines.append(dynamic_lines.pop(0)[1])

            parent_generic_id = None

            if line.parent_id:
                # Normally, the parent line has necessarily been treated in a previous iteration
                try:
                    parent_generic_id = line_cache[line.parent_id]["id"]
                except KeyError as e:
                    raise UserError(  # noqa: B904
                        _(
                            "Line '%(child)s' is configured to appear before its parent '%(parent)s'. This is not allowed.",
                            child=line.name,
                            parent=e.args[0].name,
                        )
                    )

            line_dict = self._get_static_line_dict(
                options,
                line,
                all_column_groups_expression_totals,
                parent_id=parent_generic_id,
            )
            line_cache[line] = line_dict

            if line.hide_if_zero:
                hide_if_zero_lines += line

            lines.append(line_dict)

        for _dummy, left_dynamic_line in dynamic_lines:
            lines.append(left_dynamic_line)

        # Manage growth comparison
        if options.get("column_percent_comparison") == "growth":
            for line in lines:
                if options["comparison"]["period_order"] == "descending":
                    first_value, second_value = (
                        line["columns"][0]["no_format"],
                        line["columns"][1]["no_format"],
                    )
                else:
                    first_value, second_value = (
                        line["columns"][1]["no_format"],
                        line["columns"][0]["no_format"],
                    )

                green_on_positive = True
                model, line_id = self._get_model_info_from_id(line["id"])

                if model == "account.report.line" and line_id:
                    report_line = self.env["account.report.line"].browse(line_id)
                    compared_expression = report_line.expression_ids.filtered(
                        lambda expr: (
                            expr.label == line["columns"][0]["expression_label"]  # noqa: B023
                        )
                    )
                    green_on_positive = compared_expression.green_on_positive

                line["column_percent_comparison_data"] = (
                    self._compute_column_percent_comparison_data(
                        options,
                        first_value,
                        second_value,
                        green_on_positive=green_on_positive,
                    )
                )
        # Manage budget comparison
        elif options.get("column_percent_comparison") == "budget":
            for line in lines:
                self._set_budget_column_comparisons(options, line)

        elif options.get("column_percent_comparison") == "analytic_coverage":
            for line in lines:
                first_value, second_value = (
                    line["columns"][0]["no_format"],
                    line["columns"][1]["no_format"],
                )
                line["column_percent_comparison_data"] = (
                    self._compute_column_percent_comparison_data(
                        options, first_value, second_value, green_on_positive=False
                    )
                )

        # Manage hide_if_zero lines:
        # - If they have column values: hide them if all those values are 0 (or empty)
        # - If they don't: hide them if all their children's column values are 0 (or empty)
        # Also, hide all the children of a hidden line.
        hidden_lines_dict_ids = set()
        for line in hide_if_zero_lines:
            children_to_check = line
            current = line
            while current:
                children_to_check |= current
                current = current.children_ids

            all_children_zero = True
            hide_candidates = set()
            for child in children_to_check:
                child_line_dict_id = line_cache[child]["id"]

                if child_line_dict_id in hidden_lines_dict_ids:
                    continue
                if all(
                    col.get("is_zero", True) for col in line_cache[child]["columns"]
                ):
                    hide_candidates.add(child_line_dict_id)
                else:
                    all_children_zero = False
                    break

            if all_children_zero:
                hidden_lines_dict_ids |= hide_candidates

        lines[:] = filter(
            lambda x: (
                x["id"] not in hidden_lines_dict_ids
                and x.get("parent_id") not in hidden_lines_dict_ids
            ),
            lines,
        )

        # Create the hierarchy of lines if necessary
        if options.get("hierarchy"):
            lines = self._create_hierarchy(lines, options)

        # Clean up before generating totals, so _add_totals_below_sections doesn't create
        # a total line for a parent whose children were all hidden.
        if hidden_lines_dict_ids:
            lines = self._cleanup_empty_sections(lines)

        # Handle totals below sections for static lines
        lines = self._add_totals_below_sections(lines, options)

        # Unfold lines (static or dynamic) if necessary and add totals below section to dynamic lines
        lines = self._fully_unfold_lines_if_needed(lines, options)

        if self.allow_account_audit_status_on_lines:
            lines = self._add_account_status_on_lines(lines, options)

        self._inject_account_names_for_consolidation(lines)

        if self.custom_handler_model_id:
            lines = self.env[self.custom_handler_model_name]._custom_line_postprocessor(
                self, options, lines
            )

        if warnings is not None:
            custom_handler_name = (
                self.custom_handler_model_name
                or self.root_report_id.custom_handler_model_name
            )
            if custom_handler_name:
                self.env[custom_handler_name]._customize_warnings(
                    self, options, all_column_groups_expression_totals, warnings
                )

        # Format values in columns of lines that will be displayed
        self._format_column_values(options, lines)

        if options.get("export_mode") == "print" and options.get("hide_0_lines"):
            lines = self._filter_out_0_lines(lines)
            lines = self._cleanup_empty_sections(lines)

        if options.get("export_mode") != "file":
            self._postprocess_chatter_for_annotations(lines)

        return lines

    # Deprecated, removed in master.
    @api.model
    def format_column_values(self, options, lines):
        self._format_column_values(options, lines, force_format=True)

        return lines

    def format_column_values_from_client(self, options, lines):
        """Format column values for display. Called via dispatch_report_action when rounding unit changes on client side."""
        self._format_column_values(options, lines, force_format=True)

        return lines

    def _format_column_values(self, options, line_dict_list, force_format=False):
        for line_dict in line_dict_list:
            for column_dict in line_dict["columns"]:
                if "name" in column_dict and not force_format:
                    # Columns which have already received a name are assumed to be already formatted; nothing needs to be done for them.
                    # This gives additional flexibility to custom reports, if needed.
                    continue

                if not column_dict:
                    continue
                if column_dict.get("is_zero") and column_dict.get("blank_if_zero"):
                    rslt = ""
                elif options.get("export_mode") == "file":
                    rslt = column_dict.get("no_format", "")
                else:
                    rslt = self.format_value(
                        options,
                        column_dict.get("no_format"),
                        column_dict.get("figure_type"),
                        format_params=column_dict.get("format_params"),
                    )

                column_dict["name"] = rslt

            # Handle the total in case of an horizontal group when there is no comparison and only one level of horizontal group
            if options.get("show_horizontal_group_total"):
                # In case the line has no formula
                if all(column["no_format"] is None for column in line_dict["columns"]):
                    continue
                # In case total below section, some line don't have the value displayed
                if (
                    self.env.company.totals_below_sections
                    and not options.get("ignore_totals_below_sections")
                    and line_dict["unfolded"]
                ):
                    continue

                figure_type_is_valid = all(
                    column["figure_type"] in {"float", "integer", "monetary"}
                    for column in line_dict["columns"]
                )
                total_value = (
                    sum(column["no_format"] for column in line_dict["columns"])
                    if figure_type_is_valid
                    else None
                )
                line_dict["horizontal_group_total_data"] = {
                    "name": self.format_value(
                        options,
                        total_value,
                        line_dict["columns"][0]["figure_type"],
                        format_params=line_dict["columns"][0]["format_params"],
                    ),
                    "no_format": total_value,
                }

    @api.model
    def _prepare_static_line_columns(
        self, line, options, all_column_groups_expression_totals, groupby_model=None
    ):
        line_expressions_map = {expr.label: expr for expr in line.expression_ids}
        # The totals of a line only depend on its column group, not on the individual
        # column, so resolve them once per group rather than once per column.
        reportable_expressions = [
            expr
            for expr in line.expression_ids
            if not expr.label.startswith("_default")
        ]
        line_res_dict_per_col_group = {
            col_group_key: {
                expr.label: all_column_groups_expression_totals[col_group_key][expr]
                for expr in reportable_expressions
            }
            for col_group_key in {
                column_data["column_group_key"] for column_data in options["columns"]
            }
        }
        columns = []
        for column_data in options["columns"]:
            col_group_key = column_data["column_group_key"]
            target_line_res_dict = line_res_dict_per_col_group[col_group_key]

            column_expr_label = column_data["expression_label"]
            column_res_dict = target_line_res_dict.get(column_expr_label, {})
            column_value = column_res_dict.get("value")
            column_has_sublines = column_res_dict.get("sublines_info", False)
            column_expression = line_expressions_map.get(
                column_expr_label, self.env["account.report.expression"]
            )
            figure_type = column_expression.figure_type or column_data["figure_type"]

            # Handle info popup
            info_popup_data = {}

            # Check carryover
            carryover_expr_label = "_carryover_%s" % column_expr_label
            carryover_value = target_line_res_dict.get(carryover_expr_label, {}).get(
                "value", 0
            )
            if self.env.company.currency_id.compare_amounts(0, carryover_value) != 0:
                info_popup_data["carryover"] = self._format_value(
                    options, carryover_value, "monetary"
                )

                carryover_expression = line_expressions_map[carryover_expr_label]
                if carryover_expression.carryover_target:
                    info_popup_data["carryover_target"] = (
                        carryover_expression._get_carryover_target_expression(
                            options
                        ).report_line_name
                    )
                # If it's not set, it means the carryover needs to target the same expression

            applied_carryover_value = target_line_res_dict.get(
                "_applied_carryover_%s" % column_expr_label, {}
            ).get("value", 0)
            if (
                self.env.company.currency_id.compare_amounts(0, applied_carryover_value)
                != 0
            ):
                info_popup_data["applied_carryover"] = self._format_value(
                    options, applied_carryover_value, "monetary"
                )
                info_popup_data["allow_carryover_audit"] = self.env.user.has_group(
                    "base.group_no_one"
                )
                info_popup_data["expression_id"] = line_expressions_map[
                    "_applied_carryover_%s" % column_expr_label
                ]["id"]
                info_popup_data["column_group_key"] = col_group_key

            # Handle manual edition popup
            edit_popup_data = {}
            formatter_params = {}
            if float_rounding_opt := options.get("float_rounding"):
                # This option key allows forcing the rounding of "float' figure type, to include more or less decimals
                formatter_params["digits"] = float_rounding_opt

            if (
                column_expression.engine == "external"
                and column_expression.subformula
                and len(options["companies"]) == 1
            ):
                # Compute rounding for manual values
                rounding = None
                if figure_type == "integer":
                    rounding = 0
                else:
                    rounding_opt_match = re.search(
                        r"\Wrounding\W*=\W*(?P<rounding>\d+)",
                        column_expression.subformula,
                    )
                    if rounding_opt_match:
                        rounding = int(rounding_opt_match.group("rounding"))
                    elif figure_type == "monetary":
                        rounding = self.env.company.currency_id.decimal_places

                if "editable" in column_expression.subformula:
                    edit_popup_data = {
                        "column_group_key": col_group_key,
                        "target_expression_id": column_expression.id,
                        "rounding": rounding,
                        "figure_type": figure_type,
                        "column_value": self.env.company.currency_id.round(column_value)
                        if figure_type == "monetary" and column_value
                        else column_value,
                    }

                formatter_params["digits"] = rounding

            # Handle editable financial budgets
            editable_budget = groupby_model == "account.account" and options[
                "column_groups"
            ][col_group_key]["forced_options"].get("compute_budget")
            if editable_budget and self.env.user.has_group(
                "account.group_account_manager"
            ):
                edit_popup_data = {
                    "column_group_key": col_group_key,
                    "target_expression_id": column_expression.id,
                    "rounding": self.env.company.currency_id.decimal_places,
                    "figure_type": "monetary",
                    "column_value": self.env.company.currency_id.round(column_value)
                    if column_value
                    else column_value,
                }

            # Build result
            if (
                column_value is not None
            ):  # In case column value is zero, we still want to go through the condition
                foreign_currency_id = target_line_res_dict.get(
                    f"_currency_{column_expr_label}", {}
                ).get("value")
                if foreign_currency_id:
                    formatter_params["currency"] = self.env["res.currency"].browse(
                        foreign_currency_id
                    )

            column_data = self._prepare_column_dict(
                column_value,
                column_data,
                options=options,
                column_expression=column_expression or None,
                has_sublines=column_has_sublines,
                report_line_id=line.id,
                **formatter_params,
            )

            if info_popup_data:
                column_data["info_popup_data"] = json.dumps(info_popup_data)

            if edit_popup_data:
                column_data["edit_popup_data"] = json.dumps(edit_popup_data)

            columns.append(column_data)

        return columns

    def _prepare_column_dict(
        self,
        col_value,
        col_data,
        options=None,
        currency=False,
        digits=1,
        column_expression=None,
        has_sublines=False,
        report_line_id=None,
    ):
        # Empty column
        if col_value is None and col_data is None:
            return {}

        col_data = col_data or {}
        column_expression = column_expression or self.env["account.report.expression"]
        options = options or {}

        blank_if_zero = column_expression.blank_if_zero or col_data.get(
            "blank_if_zero", False
        )
        figure_type = column_expression.figure_type or col_data.get(
            "figure_type", "string"
        )

        format_params = {}
        if figure_type == "monetary" and currency:
            format_params["currency_id"] = currency.id
        elif figure_type in ("float", "percentage"):
            format_params["digits"] = digits

        col_group_key = col_data.get("column_group_key")

        return {
            "auditable": col_value is not None
            and column_expression.auditable
            and not options["column_groups"][col_group_key]["forced_options"].get(
                "compute_budget"
            ),
            "blank_if_zero": blank_if_zero,
            "column_group_key": col_group_key,
            "currency": currency,
            "currency_symbol": (currency or self.env.company.currency_id).symbol
            if options.get("multi_currency")
            else None,
            "digits": digits,
            "expression_label": col_data.get("expression_label"),
            "figure_type": figure_type,
            "green_on_positive": column_expression.green_on_positive,
            "has_sublines": has_sublines,
            "is_zero": col_value is None
            or (
                isinstance(col_value, (int, float))
                and figure_type in NUMBER_FIGURE_TYPES
                and self._is_value_zero(
                    col_value, figure_type, format_params, options.get("rounding_unit")
                )
            ),
            "no_format": col_value,
            "format_params": format_params,
            "report_line_id": report_line_id,
            "sortable": col_data.get("sortable", False),
            "comparison_mode": col_data.get("comparison_mode"),
        }

    def _get_column_group_options(self, options, group_key):
        column_group = options["column_groups"][group_key]
        return {
            **options,
            **column_group["forced_options"],
            "forced_domain": options.get("forced_domain", [])
            + column_group["forced_domain"]
            + column_group["forced_options"].get("forced_domain", []),
            "owner_column_group": group_key,
        }

    @api.model
    @api.readonly
    def sort_lines(self, lines, options, result_as_index=False):
        """Sort report lines based on the 'order_column' key inside the options.
        The value of options['order_column'] is a dict with keys 'expression_label' (the column to sort on)
        and 'direction' ('ASC' or 'DESC').
        If this key is missing or falsy, lines is returned directly.

        This method has some limitations:

            - The selected_column must have 'sortable' in its classes.
            - All lines are sorted except:

                - lines having the 'total' class
                - lines with the 'load_more' markup
                - static lines (lines with model 'account.report.line')

            - This only works when each line has an unique id.
            - All lines inside the selected_column must have a 'no_format' value.

        Sorting is hierarchical: sibling children are sorted within their parent, and the
        parents themselves are sorted relative to each other, total lines staying last.

        :param lines:   The report lines.
        :param options: The report options.
        :return:        Lines sorted by the selected column.
        """

        def needs_to_be_at_bottom(line_elem):
            return self._get_markup(line_elem.get("id")) in ("total", "load_more")

        def _cell_value(line_dict):
            cells = line_dict["columns"]
            if column_index >= len(cells):
                return None
            return cells[column_index].get("no_format")

        def compare_values(a_line, b_line):
            type_seq = {
                type(None): 0,
                bool: 1,
                float: 2,
                int: 2,
                str: 3,
                datetime.date: 4,
                datetime.datetime: 5,
            }

            a_line_dict = lines[a_line] if result_as_index else a_line
            b_line_dict = lines[b_line] if result_as_index else b_line
            a_total = needs_to_be_at_bottom(a_line_dict)
            b_total = needs_to_be_at_bottom(b_line_dict)
            a_model = self._get_model_info_from_id(a_line_dict["id"])[0]
            b_model = self._get_model_info_from_id(b_line_dict["id"])[0]

            # static lines are not sorted
            if a_model == b_model == "account.report.line":
                return 0

            if a_total:
                if b_total:  # a_total & b_total
                    return 0
                else:  # a_total & !b_total
                    return -1 if descending else 1
            if b_total:  # => !a_total & b_total
                return 1 if descending else -1

            # A line is free to carry fewer cells than options["columns"] declares --
            # the journal report's tax section headings carry none at all -- so read
            # the cell defensively and let a missing one land in the None bucket
            # below rather than raising IndexError.
            a_val = _cell_value(a_line_dict)
            b_val = _cell_value(b_line_dict)
            # A custom handler is free to put any type in a column; sort what the table
            # does not know about after everything it does, rather than raising.
            type_a = type_seq.get(type(a_val), len(type_seq))
            type_b = type_seq.get(type(b_val), len(type_seq))

            if type_a == type_b:
                return 0 if a_val == b_val else 1 if a_val > b_val else -1
            else:
                return type_a - type_b

        def merge_tree(tree_elem, ls):
            ls.append(tree_elem)

            elem = (
                tree[lines[tree_elem]["id"]]
                if result_as_index
                else tree[tree_elem["id"]]
            )

            for tree_subelem in sorted(elem, key=comp_key, reverse=descending):
                merge_tree(tree_subelem, ls)

        # This is called straight from the client with client-supplied options, so an
        # order_column that names nothing is reachable input. Returning the lines
        # untouched is what the docstring promises; sorting on a column that was never
        # found makes every comparison equal and collapses the tree walk, which drops
        # all but one line.
        order_column = options.get("order_column") or {}
        column_index = next(
            (
                index
                for index, col in enumerate(options["columns"])
                if order_column.get("expression_label") == col["expression_label"]
            ),
            None,
        )
        if column_index is None:
            return list(range(len(lines))) if result_as_index else lines

        descending = (
            order_column.get("direction") == "DESC"
        )  # To keep total lines at the end, used in compare_values & merge_tree scopes

        comp_key = cmp_to_key(compare_values)
        sorted_list = []
        tree = defaultdict(list)
        line_ids = {line["id"] for line in lines}

        for index, line in enumerate(lines):
            line_parent = line.get("parent_id") or None

            if result_as_index:
                tree[line_parent].append(index)
            else:
                tree[line_parent].append(line)

        # A line is a root when its parent is not itself in the list: either it has
        # no parent at all, or the parent was not rendered -- the groupby line being
        # unfolded, or the hierarchy's own root, which is referenced but never
        # emitted. Picking the roots by reachability rather than by the None
        # sentinel is what makes "every line comes back" structural; keying on None
        # alone returned an empty list for every multi-root list, silently dropping
        # all of them.
        roots = [
            tree_elem
            for parent, tree_elems in tree.items()
            if parent not in line_ids
            for tree_elem in tree_elems
        ]

        for line in sorted(roots, key=comp_key, reverse=descending):
            merge_tree(line, sorted_list)

        return sorted_list

    def _get_column_headers_render_data(self, options):
        column_headers_render_data = {}

        # We only want to consider the columns that are visible in the current report and don't rely on self.column_ids
        # since custom reports could alter them (e.g. for multi-currency purposes)
        columns = [
            col
            for col in options["columns"]
            if col["column_group_key"] == next(k for k in options["column_groups"])
        ]

        # Compute the colspan of each header level, aka the number of single columns it contains at the base of the hierarchy
        level_colspan_list = column_headers_render_data["level_colspan"] = []
        for i in range(len(options["column_headers"])):
            nb_columns = max(len(columns), 1)
            colspan = nb_columns
            budget_col_number = 0

            for level_header in options["column_headers"][i + 1 :]:
                # Separate non-budget and budget headers
                budget_base_count = sum(
                    1
                    for header in level_header
                    if header.get("forced_options", {}).get("budget_base")
                )
                budget_amount_and_percentage_count = sum(
                    any(
                        key in header.get("forced_options", {})
                        for key in ("compute_budget", "budget_percentage")
                    )
                    for header in level_header
                )
                non_budget_count = (
                    len(level_header)
                    - budget_base_count
                    - budget_amount_and_percentage_count
                )

                # budget headers (amount and percentage) can only contain a single column each, regardless of the amount of columns in the report.
                # This implies that we first need to multiply for the 'regular' columns and then add the budget columns.
                colspan *= non_budget_count
                budget_col_number += (
                    budget_base_count * nb_columns
                ) + budget_amount_and_percentage_count

            level_colspan_list.append(colspan + budget_col_number)

        # Compute the number of times each header level will have to be repeated, and its colspan to properly handle horizontal groups/comparisons
        column_headers_render_data["level_repetitions"] = []
        for i in range(len(options["column_headers"])):
            colspan = 1
            for column_header in options["column_headers"][:i]:
                valid_headers_length = sum(
                    1
                    for item in column_header
                    if "no_subheader_division" not in item.get("forced_options", {})
                )
                colspan *= valid_headers_length
            column_headers_render_data["level_repetitions"].append(colspan)

        # Custom reports have the possibility to define custom subheaders that will be displayed between the generic header and the column names.
        column_headers_render_data["custom_subheaders"] = options.get(
            "custom_columns_subheaders", []
        ) * len(options["column_groups"])

        return column_headers_render_data

    def _expand_unfoldable_line(
        self,
        expand_function_name,
        line_dict_id,
        groupby,
        options,
        progress,
        offset,
        horizontal_split_side,
        unfold_all_batch_data=None,
    ):
        if not expand_function_name:
            raise UserError(_("Trying to expand a line without an expansion function."))

        if not progress:
            progress = dict.fromkeys(options["column_groups"], 0)

        expand_function = self._get_custom_report_function(
            expand_function_name, "expand_unfoldable_line"
        )
        expansion_result = expand_function(
            line_dict_id,
            groupby,
            options,
            progress,
            offset,
            unfold_all_batch_data=unfold_all_batch_data,
        )

        rslt = expansion_result["lines"]

        if horizontal_split_side:
            for line in rslt:
                line["horizontal_split_side"] = horizontal_split_side

        # Apply integer rounding to the result if needed.
        # The groupby expansion function is the only one guaranteed to call the expressions computation,
        # so the values computed for it will already have been rounded if integer rounding is enabled. No need to round them again.
        if expand_function_name != "_report_expand_unfoldable_line_with_groupby":
            self._apply_integer_rounding_to_dynamic_lines(options, rslt)

        if expansion_result.get("has_more"):
            # We only add load_more line for groupby
            next_offset = offset + expansion_result["offset_increment"]
            rslt.append(
                self._get_load_more_line(
                    next_offset,
                    line_dict_id,
                    expand_function_name,
                    groupby,
                    expansion_result.get("progress", 0),
                    options,
                )
            )

        # In some specific cases, we may want to add lines that are always at the end. So they need to be added after the load more line.
        if expansion_result.get("after_load_more_lines"):
            rslt.extend(expansion_result["after_load_more_lines"])

        return self._add_totals_below_sections(rslt, options)

    def _report_expand_unfoldable_line_with_groupby(
        self,
        line_dict_id,
        groupby,
        options,
        progress,
        offset,
        unfold_all_batch_data=None,
    ):
        # The line we're expanding might be an inner groupby; we first need to find the report line generating it
        report_line_id = None
        for _markup, model, model_id in reversed(self._parse_line_id(line_dict_id)):
            if model == "account.report.line":
                report_line_id = model_id
                break

        if report_line_id is None:
            raise UserError(
                _(
                    "Trying to expand a group for a line which was not generated by a report line: %s",
                    line_dict_id,
                )
            )

        line = self.env["account.report.line"].browse(report_line_id)

        if "," not in groupby and options["export_mode"] is None:
            # if ',' not in groupby, then its a terminal groupby (like 'id' in 'partner_id, id'), so we can use the 'load more' feature if necessary
            # When printing, we want to ignore the limit.
            limit_to_load = self.load_more_limit or None
        else:
            # Else, we disable it
            limit_to_load = None
            offset = 0

        rslt_lines = line._expand_groupby(
            line_dict_id,
            groupby,
            options,
            offset=offset,
            limit=limit_to_load,
            load_one_more=bool(limit_to_load),
            unfold_all_batch_data=unfold_all_batch_data,
        )
        lines_to_load = (
            rslt_lines[: self.load_more_limit] if limit_to_load else rslt_lines
        )

        if not limit_to_load and options["export_mode"] is None:
            lines_to_load = self._regroup_lines_by_name_prefix(
                options,
                rslt_lines,
                "_report_expand_unfoldable_line_groupby_prefix_group",
                line.hierarchy_level,
                groupby=groupby,
                parent_line_dict_id=line_dict_id,
            )

        return {
            "lines": lines_to_load,
            "offset_increment": len(lines_to_load),
            "has_more": len(lines_to_load) < len(rslt_lines)
            if limit_to_load
            else False,
        }

    def _regroup_lines_by_name_prefix(
        self,
        options,
        lines_to_group,
        expand_function_name,
        parent_level,
        matched_prefix="",
        groupby=None,
        parent_line_dict_id=None,
    ):
        """Postprocesses a list of report line dictionaries in order to regroup them by name prefix and reduce the overall number of lines
        if their number is above a provided threshold (set in the report configuration).

        The lines regrouped under a common prefix will be removed from the returned list of lines; only the prefix line will stay, folded.
        Its expand function must ensure the right sublines are reloaded when unfolding it.

        :param options: Option dict for this report.
        :param lines_to_group: The lines list to regroup by prefix if necessary. They must all have the same parent line (which might be no line at all).
        :param expand_function_name: Name of the expand function to be called on created prefix group lines, when unfolding them
        :param parent_level: Level of the parent line, which generated the lines in lines_to_group. It will be used to compute the level of the prefix group lines.
        :param matched_prefix: A string containing the parent prefix that's already matched. For example, when computing prefix 'ABC', matched_prefix will be 'AB'.
        :param groupby: groupby value of the parent line, which generated the lines in lines_to_group.
        :param parent_line_dict_id: id of the parent line, which generated the lines in lines_to_group.

        :return: lines_to_group, grouped by prefix if it was necessary.
        """
        threshold = options["prefix_groups_threshold"]

        # When grouping by prefix, we ignore the totals
        lines_to_group_without_totals = list(
            filter(lambda x: self._get_markup(x["id"]) != "total", lines_to_group)
        )

        if (
            options["export_mode"] == "print"
            or threshold <= 0
            or len(lines_to_group_without_totals) < threshold
        ):
            # No grouping needs to be done
            return lines_to_group

        char_index = len(matched_prefix)
        prefix_groups = defaultdict(list)
        rslt = []
        for line in lines_to_group_without_totals:
            line_name = line["name"].strip()

            if len(line_name) - 1 < char_index:
                rslt.append(line)
            else:
                prefix_groups[line_name[char_index].lower()].append(line)

        float_figure_types = {"monetary", "integer", "float"}
        unfold_all = options["export_mode"] == "print" or options.get("unfold_all")
        for prefix_key, prefix_sublines in sorted(
            prefix_groups.items(), key=lambda x: x[0]
        ):
            # Compute the total of this prefix line, summming all of its content
            prefix_expression_totals_by_group = {}
            for column_index, column_data in enumerate(options["columns"]):
                if column_data["figure_type"] in float_figure_types:
                    # Then we want to sum this column's value in our children
                    for prefix_subline in prefix_sublines:
                        prefix_expr_label_result = (
                            prefix_expression_totals_by_group.setdefault(
                                column_data["column_group_key"], {}
                            )
                        )
                        prefix_expr_label_result.setdefault(
                            column_data["expression_label"], 0
                        )
                        prefix_expr_label_result[column_data["expression_label"]] += (
                            prefix_subline["columns"][column_index].get("no_format")
                            or 0
                        )

            column_values = []
            for column in options["columns"]:
                col_value = prefix_expression_totals_by_group.get(
                    column["column_group_key"], {}
                ).get(column["expression_label"])

                column_values.append(
                    self._prepare_column_dict(col_value, column, options=options)
                )

            line_id = self._get_generic_line_id(
                None,
                None,
                parent_line_id=parent_line_dict_id,
                markup={"groupby_prefix_group": prefix_key},
            )

            sublines_nber = len(prefix_sublines)
            prefix_to_display = prefix_key.upper()

            if re.match(r"\s", prefix_to_display[-1]):
                # In case the last character of the prefix to_display is blank, replace it by "[ ]", to make the space more visible to the user.
                prefix_to_display = f"{prefix_to_display[:-1]}[ ]"

            if sublines_nber == 1:
                prefix_group_line_name = f"{matched_prefix}{prefix_to_display} " + _(
                    "(1 line)"
                )
            else:
                prefix_group_line_name = f"{matched_prefix}{prefix_to_display} " + _(
                    "(%s lines)", sublines_nber
                )

            prefix_group_line = {
                "id": line_id,
                "name": prefix_group_line_name,
                "unfoldable": True,
                "unfolded": unfold_all or line_id in options["unfolded_lines"],
                "columns": column_values,
                "groupby": groupby,
                "level": parent_level + 1,
                "parent_id": parent_line_dict_id,
                "expand_function": expand_function_name,
                "hide_line_buttons": True,
            }
            rslt.append(prefix_group_line)

        return rslt

    def _report_expand_unfoldable_line_groupby_prefix_group(
        self,
        line_dict_id,
        groupby,
        options,
        progress,
        offset,
        unfold_all_batch_data=None,
    ):
        """Expand function used by prefix_group lines generated for groupby lines."""
        report_line_id = None
        parent_groupby_count = 0
        for markup, model, model_id in reversed(self._parse_line_id(line_dict_id)):
            if model == "account.report.line":
                report_line_id = model_id
                break
            if (
                isinstance(markup, dict) and "groupby" in markup
            ) or "groupby_prefix_group" in markup:
                parent_groupby_count += 1

        if report_line_id is None:
            raise UserError(
                _(
                    "Trying to expand a group for a line which was not generated by a report line: %s",
                    line_dict_id,
                )
            )

        report_line = self.env["account.report.line"].browse(report_line_id)

        matched_prefix = self._get_prefix_groups_matched_prefix_from_line_id(
            line_dict_id
        )
        first_groupby = groupby.split(",")[0]
        expand_options = {
            **options,
            "forced_domain": options.get("forced_domain", [])
            + [
                (
                    f"{f'{first_groupby}.' if first_groupby != 'id' else ''}name",
                    "=ilike",
                    f"{matched_prefix}%",
                )
            ],
        }
        expanded_groupby_lines = report_line._expand_groupby(
            line_dict_id, groupby, expand_options
        )
        parent_level = report_line.hierarchy_level + parent_groupby_count * 2

        lines = self._regroup_lines_by_name_prefix(
            options,
            expanded_groupby_lines,
            "_report_expand_unfoldable_line_groupby_prefix_group",
            parent_level,
            groupby=groupby,
            matched_prefix=matched_prefix,
            parent_line_dict_id=line_dict_id,
        )

        return {
            "lines": lines,
            "offset_increment": len(lines),
            "has_more": False,
        }
