from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class TradeDirection:
    key: Literal["sale", "purchase"]
    move_prefix: Literal["out", "in"]
    price_sign: Literal[1, -1]
    partner_usage: Literal["customer", "supplier"]
    partner_side: Literal["destination", "source"]
    product_ok_field: str
    product_taxes_field: str
    partner_payment_term_field: str
    invoice_policy_field: str
    transfer_verb: str

    @property
    def move_types(self) -> tuple[str, str]:
        return (f"{self.move_prefix}_invoice", f"{self.move_prefix}_refund")

    @property
    def partner_location_field(self) -> str:
        return (
            "location_dest_id" if self.partner_side == "destination" else "location_id"
        )

    @property
    def analytic_business_domain(self) -> str:
        return f"{self.key}_order"


SALE = TradeDirection(
    key="sale",
    move_prefix="out",
    price_sign=1,
    partner_usage="customer",
    partner_side="destination",
    product_ok_field="sale_ok",
    product_taxes_field="taxes_id",
    partner_payment_term_field="property_payment_term_id",
    invoice_policy_field="invoice_policy",
    transfer_verb="delivered",
)

PURCHASE = TradeDirection(
    key="purchase",
    move_prefix="in",
    price_sign=-1,
    partner_usage="supplier",
    partner_side="source",
    product_ok_field="purchase_ok",
    product_taxes_field="supplier_taxes_id",
    partner_payment_term_field="property_supplier_payment_term_id",
    invoice_policy_field="bill_policy",
    transfer_verb="received",
)


def direction_of(model) -> TradeDirection:
    direction = model._direction
    if direction is None:
        raise NotImplementedError(f"{model._name} must declare _direction")
    return direction
