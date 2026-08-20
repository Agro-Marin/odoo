# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import re

from odoo import api, models
from odoo.fields import Domain
from odoo.tools import escape_psql

from odoo.addons.website.tools import text_from_html

logger = logging.getLogger(__name__)


class MixinWebsiteSearchable(models.AbstractModel):
    """Mixin to be inherited by all models that need to searchable through website"""

    _name = "mixin.website.searchable"
    _description = "Website Searchable Mixin"

    @api.model
    def _search_build_domain(self, domain_list, search, fields, extra=None):
        """
        Builds a search domain AND-combining a base domain with partial matches of each term in
        the search expression in any of the fields.

        :param domain_list: base domain list combined in the search expression
        :param search: search expression string
        :param fields: list of field names to match the terms of the search expression with
        :param extra: function that returns an additional subdomain for a search term

        :return: domain limited to the matches of the search expression
        """
        domain = Domain.AND(domain_list)
        if search:
            for search_term in search.split():
                subdomains = [
                    Domain(field, "ilike", escape_psql(search_term)) for field in fields
                ]
                if extra:
                    subdomains.append(extra(self.env, search_term))
                domain &= Domain.OR(subdomains)
        return domain

    @api.model
    def _search_get_detail(self, website, order, options):
        """
        Returns indications on how to perform the searches

        :param website: website within which the search is done
        :param order: order in which the results are to be returned
        :param options: search options

        :return: search detail as expected in elements of the result of website._search_get_details()
            These elements contain the following fields:
            - model: name of the searched model
            - base_domain: list of domains within which to perform the search
            - search_fields: fields within which the search term must be found
            - fetch_fields: fields from which data must be fetched
            - mapping: mapping from the results towards the structure used in rendering templates.
                The mapping is a dict that associates the rendering name of each field
                to a dict containing the 'name' of the field in the results list and the 'type'
                that must be used for rendering the value
            - icon: name of the icon to use if there is no image

        This method must be implemented by all models that inherit this mixin.
        """
        raise NotImplementedError

    @api.model
    def _search_fetch(self, search_detail, search, limit, order):
        fields = search_detail["search_fields"]
        base_domain = search_detail["base_domain"]
        domain = self._search_build_domain(
            base_domain, search, fields, search_detail.get("search_extra")
        )
        model = self.sudo() if search_detail.get("requires_sudo") else self
        results = model.search(
            domain, limit=limit, order=search_detail.get("order", order)
        )
        count = (
            model.search_count(domain)
            if limit and limit == len(results)
            else len(results)
        )
        return results, count

    def _search_render_results(self, fetch_fields, mapping, icon, limit):
        results_data = self.read(fetch_fields)[:limit]
        for result in results_data:
            result["_fa"] = icon
            result["_mapping"] = mapping
        html_fields = [
            config["name"] for config in mapping.values() if config.get("html")
        ]
        if html_fields:
            for data in results_data:
                for html_field in html_fields:
                    if data[html_field]:
                        if html_field == "arch":
                            # Undo second escape of text nodes from wywsiwyg.js _getEscapedElement.
                            data[html_field] = re.sub(
                                r"&amp;(?=\w+;)", "&", data[html_field]
                            )
                        text = text_from_html(data[html_field], True)
                        data[html_field] = text
        return results_data
