from odoo import http
from odoo.http import request


class WebsiteUrl(http.Controller):
    @http.route("/website_links/new", type="jsonrpc", auth="user", methods=["POST"])
    def create_shorten_url(self, **post):
        if "url" not in post or post["url"] == "":
            return {"error": "empty_url"}
        # This one link is created interactively and its title is shown straight
        # away, so it is worth the fetch that `link.tracker.create` no longer does
        # on its own -- a mailing send creating twenty links is not.
        return (
            request.env["link.tracker"]
            .with_context(link_tracker_fetch_title=True)
            .search_or_create([post])
            .read()
        )

    @http.route("/r", type="http", auth="user", website=True)
    def shorten_url(self, **post):
        return request.render(
            "website_links.page_shorten_url",
            {
                "can_create_link_tracker": request.env["link.tracker"].has_access(
                    "create"
                ),
                "can_create_link_tracker_code": request.env[
                    "link.tracker.code"
                ].has_access("create"),
                **post,
            },
        )

    @http.route("/website_links/add_code", type="jsonrpc", auth="user")
    def add_code(self, **post):
        link_id = (
            request.env["link.tracker.code"]
            .search([("code", "=", post["init_code"])], limit=1)
            .link_id.id
        )
        # `search_count` returns an int, and this branch used to call `.read()` on
        # it -- so asking for a code the link already carries raised AttributeError
        # instead of returning that code.
        existing = request.env["link.tracker.code"].search(
            [("code", "=", post["new_code"]), ("link_id", "=", link_id)], limit=1
        )
        if existing:
            return existing.read()
        return (
            request.env["link.tracker.code"]
            .create({"code": post["new_code"], "link_id": link_id})
            .read()
        )

    @http.route("/website_links/recent_links", type="jsonrpc", auth="user")
    def recent_links(self, **post):
        return request.env["link.tracker"].recent_links(post["filter"], post["limit"])

    @http.route("/r/<string:code>+", type="http", auth="user", website=True)
    def statistics_shorten_url(self, code, **post):
        code = request.env["link.tracker.code"].search([("code", "=", code)], limit=1)

        if code:
            return request.render(
                "website_links.graphs",
                {
                    "can_create_link_tracker_code": request.env[
                        "link.tracker.code"
                    ].has_access("create"),
                    **code.link_id.read()[0],
                },
            )
        else:
            return request.redirect("/", code=301)
