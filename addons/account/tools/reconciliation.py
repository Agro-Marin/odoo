def amount_range_after_rate(currency_from, currency_to, amount, rate):
    if not rate:
        return 0.0, 0.0, 0.0
    half_rounding = currency_from.rounding / 2
    return (
        currency_to.round((amount - half_rounding) * rate),
        currency_to.round(amount * rate),
        currency_to.round((amount + half_rounding) * rate),
    )


def pick_reconciliation_currency(
    debit_currency,
    credit_currency,
    company_currency,
    debit_available,
    credit_available,
):
    for currency in (debit_currency, credit_currency):
        if (
            currency != company_currency
            and currency in debit_available
            and currency in credit_available
        ):
            return currency
    return company_currency


def group_lines_by_matching_number(partial_edges):
    """Map each connected component of reconciled lines to its oldest partial id.

    ``partial_edges`` yields ``(partial_id, debit_line_id, credit_line_id)``.
    Two lines belong to the same component when a chain of partials links them,
    and the component is numbered by the smallest partial id it contains.
    """
    parent = {}
    component_size = {}
    component_number = {}

    def find(line_id):
        root_id = line_id
        while parent[root_id] != root_id:
            root_id = parent[root_id]
        while parent[line_id] != line_id:
            next_id = parent[line_id]
            parent[line_id] = root_id
            line_id = next_id
        return root_id

    for partial_id, debit_id, credit_id in partial_edges:
        for line_id in (debit_id, credit_id):
            if line_id not in parent:
                parent[line_id] = line_id
                component_size[line_id] = 1
                component_number[line_id] = partial_id

        debit_root = find(debit_id)
        credit_root = find(credit_id)
        if debit_root == credit_root:
            component_number[debit_root] = min(component_number[debit_root], partial_id)
            continue

        if component_size[debit_root] < component_size[credit_root]:
            debit_root, credit_root = credit_root, debit_root
        parent[credit_root] = debit_root
        component_size[debit_root] += component_size.pop(credit_root)
        component_number[debit_root] = min(
            component_number[debit_root],
            component_number.pop(credit_root),
            partial_id,
        )

    number2lines = {}
    for line_id in parent:
        root_id = find(line_id)
        number2lines.setdefault(component_number[root_id], []).append(line_id)
    return number2lines
