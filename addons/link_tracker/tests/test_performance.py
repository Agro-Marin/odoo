# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo.tests import common, tagged


@tagged('link_tracker', 'post_install', '-at_install')
class TestLinkTrackerCost(common.TransactionCase):
    """Marginal-cost tests.

    An absolute ``assertQueryCount`` at N=1 cannot see an N+1 at all, and a
    warm-cache measurement cannot see one either -- inside one transaction only
    the first record of a batch pays. Every test here compares a small N against
    a large one, with the cache dropped in between, and asserts on the *slope*.
    """

    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param('web.base.url', 'https://test.odoo.com')
        self.render = self.env['mixin.mail.render']
        # Warm whatever the first call would pay for once (config parameters,
        # registry lookups), so it is not counted as slope.
        self.render._shorten_links('<a href="https://warm.example.com">w</a>', {})
        self.env.flush_all()

    def _queries(self, func):
        self.env.flush_all()
        self.env.invalidate_all()
        before = self.env.cr.sql_log_count
        func()
        self.env.flush_all()
        return self.env.cr.sql_log_count - before

    def _body(self, count, tag):
        return "".join(
            f'<a href="https://{tag}-{index}.example.com">Link {index}</a>'
            for index in range(count)
        )

    def test_shortening_an_html_body_is_not_priced_per_link(self):
        """100 fresh links must not cost ~100 queries.

        The ORM's own insert strategy changes above a row threshold, so the count
        is not monotonic in N and a slope assertion would be noise. What is stable
        is the order of magnitude: this was 109 queries when `_compute_code` ran a
        search per record.
        """
        count = self._queries(lambda: self.render._shorten_links(self._body(100, 'html-many'), {}))
        self.assertLessEqual(
            count, 30,
            f"shortening 100 new links cost {count} queries -- that is per-link work",
        )

    def test_reshortening_a_body_costs_the_same_at_any_size(self):
        """The case a mailing actually pays: every batch after the first.

        `_action_send_mail_mass_mail` invalidates once per batch of recipients, so
        this is the cold cost each batch repeats. It is flat, and must stay flat.
        """
        small_body, large_body = self._body(2, 'again-small'), self._body(100, 'again-large')
        self.render._shorten_links(small_body, {})
        self.render._shorten_links(large_body, {})
        small = self._queries(lambda: self.render._shorten_links(small_body, {}))
        large = self._queries(lambda: self.render._shorten_links(large_body, {}))
        self.assertLessEqual(
            large - small, 1,
            f"re-shortening 98 further known links cost {large - small} extra queries "
            f"({small} for 2, {large} for 100)",
        )

    def test_shortening_a_text_body_is_not_priced_per_link(self):
        """`search_or_create` is a batch API; it was called once per URL."""
        text = " ".join(f'https://txt-many-{i}.example.com' for i in range(100))
        count = self._queries(lambda: self.render._shorten_links_text(text, {}))
        self.assertLessEqual(
            count, 30,
            f"shortening 100 new links cost {count} queries -- that is per-link work",
        )

    def test_reading_a_code_does_not_scale_with_the_recordset(self):
        """`code` feeds `short_url` and therefore `display_name`.

        Two queries per record here is two queries per row of any list showing a
        link tracker, and of any list showing a click.
        """
        trackers = self.env['link.tracker'].create(
            [{'url': f'https://code-{i}.example.com'} for i in range(20)])
        small, large = trackers[:2], trackers
        small_count = self._queries(lambda: small.mapped('code'))
        large_count = self._queries(lambda: large.mapped('code'))
        self.assertLessEqual(
            large_count - small_count, 1,
            f"reading `code` on 18 further records cost {large_count - small_count} extra "
            f"queries ({small_count} for 2, {large_count} for 20)",
        )
        display_small = self._queries(lambda: small.mapped('display_name'))
        display_large = self._queries(lambda: large.mapped('display_name'))
        self.assertLessEqual(
            display_large - display_small, 1,
            f"reading `display_name` on 18 further records cost "
            f"{display_large - display_small} extra queries",
        )

    def test_finding_known_trackers_does_not_scale_with_the_batch(self):
        """`search_or_create` resolves a whole batch through one indexed lookup."""
        def vals(count, tag):
            return [{'url': f'https://soc-{tag}-{i}.example.com'} for i in range(count)]
        small_vals, large_vals = vals(2, 'small'), vals(20, 'large')
        self.env['link.tracker'].search_or_create([dict(v) for v in small_vals])
        self.env['link.tracker'].search_or_create([dict(v) for v in large_vals])
        small = self._queries(
            lambda: self.env['link.tracker'].search_or_create([dict(v) for v in small_vals]))
        large = self._queries(
            lambda: self.env['link.tracker'].search_or_create([dict(v) for v in large_vals]))
        self.assertLessEqual(
            large - small, 1,
            f"resolving 18 further known keys cost {large - small} extra queries "
            f"({small} for 2, {large} for 20)",
        )
