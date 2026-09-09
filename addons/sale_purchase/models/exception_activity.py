def notify_orders_of_exception(order_to_lines, view_xmlid, render_context):
    for order, lines in order_to_lines.items():
        order._activity_schedule_with_view(
            "mail.mail_activity_data_warning",
            user_id=order.user_id.id or order.env.uid,
            views_or_xmlid=view_xmlid,
            render_context=render_context(lines),
        )


def group_by_order(lines, order_of):
    grouped = {}
    for line in lines:
        order = order_of(line)
        grouped.setdefault(order, line.browse())
        grouped[order] |= line
    return grouped
