"""Pure numeric helpers for the reconciliation partial-amount computation."""

# `account.move.line._prepare_reconciliation_single_partial` decides how much of
# two opposite lines can be matched, in which currency and at which rate. Most of
# that is arithmetic over residual amounts, but it lived inline in a 363-line
# method (ruff C901 = 35) reachable only through a 9 855-line database test file.
#
# These two pieces are the parts that need no ORM at all. Both take a plain
# rounding protocol rather than a `res.currency`: anything exposing `rounding`
# and `round()` will do, which is what makes them Tier-1 testable (no database,
# see doc/coding_guidelines.rst §6). The rest of the method -- residual lookup,
# exchange-difference lines, the aml field access -- stays where it is; it is
# genuinely ORM work and pretending otherwise would just move the coupling.


def amount_range_after_rate(currency_from, currency_to, amount, rate):
    """Return ``(low, mid, high)``: ``amount`` at ``rate``, as a rounding band.

    A stored amount is itself already rounded, so converting it gives a range
    rather than a point. Suppose ``balance = 1000`` at ``rate = 12``: the 1000.0
    could be the rounding of anything in ``[999.995, 1000.005]``, so the target
    is ``[999.995 * 12, 1000.005 * 12] = [11999.94, 12000.06]`` and not just
    12000.0. Callers use the band to decide whether a computed counterpart is
    "the same amount" without demanding exact float equality.

    :param currency_from: rounding source; only ``.rounding`` is read.
    :param currency_to: rounding target; only ``.round()`` is called.
    :param amount: the amount to convert.
    :param rate: conversion rate; a falsy rate yields a zero band.
    """
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
    """Choose the currency the two lines will be reconciled in.

    A foreign currency is only usable when *both* sides have a residual left in
    it -- otherwise there is nothing to match against on one of them. The debit
    side is preferred over the credit side purely for determinism, so that
    reconciling A against B picks the same currency as B against A. Company
    currency is the fallback, and always works because every line has a balance.

    :param debit_available: mapping ``currency -> residual info`` for the debit.
    :param credit_available: same, for the credit.
    :return: the chosen currency (one of the three passed in).
    """
    for currency in (debit_currency, credit_currency):
        if (
            currency != company_currency
            and currency in debit_available
            and currency in credit_available
        ):
            return currency
    return company_currency
