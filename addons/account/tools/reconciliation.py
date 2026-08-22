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
