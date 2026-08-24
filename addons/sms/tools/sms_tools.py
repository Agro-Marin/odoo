import re

import markupsafe

from odoo.tools import html_escape
from odoo.tools.mail import TEXT_URL_REGEX, create_link


def sms_content_to_rendered_html(text):
    """Transforms plaintext into html making urls clickable and preserving newlines"""
    urls = TEXT_URL_REGEX.findall(text)
    escaped_text = html_escape(text)
    for url in urls:
        escaped_text = escaped_text.replace(url, markupsafe.Markup(create_link(url, url)))
    return markupsafe.Markup(re.sub(r'\r?\n|\r', '<br/>', escaped_text))
