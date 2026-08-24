from odoo.http import request, route

from odoo.addons.mail.controllers import thread


class ThreadController(thread.ThreadController):
    @route()
    def mail_message_post(self, thread_model, thread_id, post_data, context=None, **kwargs):
        # The onboarding tour needs to know the message was sent through a canned
        # response, which is a property of the request rather than of the message.
        # Scoped to discuss.channel: odoobot only ever answers there, and the
        # context reaches every ORM call made for the rest of the request.
        if thread_model == "discuss.channel" and kwargs.get("canned_response_ids"):
            request.update_context(canned_response_ids=kwargs["canned_response_ids"])
        return super().mail_message_post(thread_model, thread_id, post_data, context, **kwargs)
