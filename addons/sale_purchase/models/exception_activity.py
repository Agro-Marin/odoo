def notify_orders_of_exception(order_to_lines, view_xmlid, render_context):
    """Schedule one warning activity per order, explained by the lines it maps to.

    :param order_to_lines: map of the order to warn to the recordset of lines
        that explain why, on the *other* side of the sale/purchase link
    :param view_xmlid: qweb view rendered as the activity note
    :param render_context: callable turning one such recordset into the view's
        render context
    """
    for order, lines in order_to_lines.items():
        order._activity_schedule_with_view(
            "mail.mail_activity_data_warning",
            user_id=order.user_id.id or order.env.uid,
            views_or_xmlid=view_xmlid,
            render_context=render_context(lines),
        )


def group_by_order(lines, order_of):
    """Group ``lines`` into a map of order -> recordset of the lines reaching it."""
    grouped = {}
    for line in lines:
        order = order_of(line)
        grouped.setdefault(order, line.browse())
        grouped[order] |= line
    return grouped
