from odoo import http
from odoo.exceptions import AccessError, MissingError, ValidationError
from odoo.fields import Command
from odoo.http import request

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment.controllers import portal as payment_portal


class PaymentPortal(payment_portal.PaymentPortal):
    """Extends the payment portal to integrate sales order-specific payment functionalities.

    This module handles payment transactions for sales orders, ensuring proper access control,
    validation, and routing to the sales order portal. It also supports partial payments and
    access token verification for secure transactions."""

    # ------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------

    def _get_extra_payment_form_values(
        self, sale_order_id=None, access_token=None, **kwargs
    ):
        """Override of `payment` to reroute the payment flow to the portal view of the sales order.

        :param str sale_order_id: The sale order for which a payment is made, as a `sale.order` id.
        :param str access_token: The portal or payment access token, respectively if we are in a
                                 portal or payment link flow.
        :return: The extended rendering context values.
        :rtype: dict"""
        form_values = super()._get_extra_payment_form_values(
            sale_order_id=sale_order_id, access_token=access_token, **kwargs
        )
        if sale_order_id:
            sale_order_id = self._cast_as_int(sale_order_id)

            try:  # Check document access against what could be a portal access token.
                order_sudo = self._document_check_access(
                    "sale.order", sale_order_id, access_token
                )
            except (
                AccessError
            ):  # It is a payment access token computed on the payment context.
                if not payment_utils.check_access_token(
                    access_token,
                    kwargs.get("partner_id"),
                    kwargs.get("amount"),
                    kwargs.get("currency_id"),
                ):
                    raise

                order_sudo = request.env["sale.order"].sudo().browse(sale_order_id)

            # Interrupt the payment flow if the sales order has been canceled.
            if order_sudo.state == "cancel":
                form_values["amount"] = 0.0

            # Reroute the next steps of the payment flow to the portal view of the sales order.
            form_values.update(
                {
                    "transaction_route": order_sudo.get_portal_url(
                        suffix="/transaction"
                    ),
                    "landing_route": order_sudo.get_portal_url(),
                    "access_token": order_sudo.access_token,
                }
            )
        return form_values

    # ------------------------------------------------------------
    # ENDPOINTS
    # ------------------------------------------------------------

    @http.route("/my/orders/<int:order_id>/transaction", type="jsonrpc", auth="public")
    def portal_order_transaction(self, order_id, access_token, **kwargs):
        """Create a draft transaction and return its processing values.

        :param int order_id: The sales order to pay, as a `sale.order` id
        :param str access_token: The access token used to authenticate the request
        :param dict kwargs: Locally unused data passed to `_create_transaction`
        :return: The mandatory values for the processing of the transaction
        :rtype: dict
        :raise: ValidationError if the invoice id or the access token is invalid"""
        # Check the order id and the access token
        try:
            order_sudo = self._document_check_access(
                "sale.order", order_id, access_token
            )
        except MissingError as error:
            raise error

        except AccessError:
            raise ValidationError(_("The access token is invalid."))

        logged_in = not request.env.user._is_public()
        partner_sudo = (
            request.env.user.partner_id if logged_in else order_sudo.partner_invoice_id
        )
        self._validate_transaction_kwargs(kwargs)
        kwargs.update(
            {
                "partner_id": partner_sudo.id,
                "currency_id": order_sudo.currency_id.id,
                "sale_order_id": order_id,  # Include the SO to allow Subscriptions tokenizing the tx
            }
        )
        tx_sudo = self._create_transaction(
            custom_create_values={"sale_order_ids": [Command.set([order_id])]},
            **kwargs,
        )
        return tx_sudo._get_processing_values()

    # Payment overrides

    @http.route()
    def payment_pay(
        self, *args, amount=None, sale_order_id=None, access_token=None, **kwargs
    ):
        """Override of `payment` to replace the missing transaction values by that of the sales
        order.

        :param str amount: The (possibly partial) amount to pay used to check the access token
        :param str sale_order_id: The sale order for which a payment id made, as a `sale.order` id
        :param str access_token: The access token used to authenticate the partner
        :return: The result of the parent method
        :rtype: str
        :raise: ValidationError if the order id is invalid"""
        # Cast numeric parameters as int or float and void them if their str value is malformed
        amount = self._cast_as_float(amount)
        sale_order_id = self._cast_as_int(sale_order_id)
        if sale_order_id:
            order_sudo = request.env["sale.order"].sudo().browse(sale_order_id).exists()

            if not order_sudo:
                raise ValidationError(_("The provided parameters are invalid."))

            # Check the access token against the order values. Done after fetching the order as we
            # need the order fields to check the access token.
            if not payment_utils.check_access_token(
                access_token,
                order_sudo.partner_invoice_id.id,
                amount,
                order_sudo.currency_id.id,
            ):
                raise ValidationError(_("The provided parameters are invalid."))

            kwargs.update(
                {
                    # To display on the payment form; will be later overwritten when creating the tx.
                    "reference": order_sudo.name,
                    # To fix the currency if incorrect and avoid mismatches when creating the tx.
                    "currency_id": order_sudo.currency_id.id,
                    # To fix the partner if incorrect and avoid mismatches when creating the tx.
                    "partner_id": order_sudo.partner_invoice_id.id,
                    "company_id": order_sudo.company_id.id,
                    "sale_order_id": sale_order_id,
                }
            )
        return super().payment_pay(
            *args, amount=amount, access_token=access_token, **kwargs
        )
