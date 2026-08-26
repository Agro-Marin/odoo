import re
from urllib.parse import urlsplit

from lxml import etree, html

from odoo.tools.misc import hmac


def distance(s1="", s2="", limit=4):
    BIG = 100000
    if len(s1) > len(s2):
        s1, s2 = s2, s1
    l1 = len(s1)
    l2 = len(s2)
    if l2 - l1 > limit:
        return -1
    boundary = min(l1, limit) + 1
    p = [i if i < boundary else BIG for i in range(l1 + 1)]
    d = [BIG for _ in range(l1 + 1)]
    for j in range(1, l2 + 1):
        j2 = s2[j - 1]
        d[0] = j
        range_min = max(1, j - limit)
        range_max = min(l1, j + limit)
        if range_min > 1:
            d[range_min - 1] = BIG
        for i in range(range_min, range_max + 1):
            if s1[i - 1] == j2:
                d[i] = p[i - 1]
            else:
                d[i] = 1 + min(d[i - 1], p[i], p[i - 1])
        p, d = d, p
    return p[l1] if p[l1] <= limit else -1


def similarity_score(s1, s2):
    dist = distance(s1, s2)
    if dist == -1:
        return -1
    if not s1 or not s2:
        return -1
    set1 = set(s1)
    score = len(set1.intersection(s2)) / len(set1)
    score -= dist / len(s1)
    score -= len(set1.symmetric_difference(s2)) / (len(s1) + len(s2))
    return score


_TEXT_EXCLUDED_XPATHS = (
    "//script",
    "//style",
    "//svg",
    '//*[@class="css_non_editable_mode_hidden"]',
)


def _drop_keeping_tail(element):
    parent = element.getparent()
    if parent is None:
        return
    if element.tail:
        previous = element.getprevious()
        if previous is not None:
            previous.tail = (previous.tail or "") + element.tail
        else:
            parent.text = (parent.text or "") + element.tail
    parent.remove(element)


def text_from_html(html_fragment, collapse_whitespace=False):
    tree = html.fromstring("<div>%s</div>" % (html_fragment or ""))

    for xpath_filter in _TEXT_EXCLUDED_XPATHS:
        for element in tree.xpath(xpath_filter):
            _drop_keeping_tail(element)

    content = " ".join(tree.itertext())
    if collapse_whitespace:
        content = re.sub(r"\s+", " ", content).strip()
    return content


def get_base_domain(url, strip_www=False):
    if not url:
        return ""

    url = urlsplit(url).netloc
    if strip_www and url.startswith("www."):
        url = url[4:]
    return url


def website_form_signature_payload(email_to, extra_recipients):
    parts = [email_to or ""]
    parts.extend(
        "%s=%s" % (name, extra_recipients[name] or "")
        for name in ("email_cc", "email_bcc")
        if name in extra_recipients
    )
    return "\x00".join(parts)


def add_form_signature(html_fragment, env_sudo):
    for form in html_fragment.iter("form"):
        if "/website/form/" not in form.attrib.get("action", ""):
            continue

        existing_hash_node = form.find(
            './/input[@type="hidden"][@name="website_form_signature"]'
        )
        if existing_hash_node is not None:
            existing_hash_node.getparent().remove(existing_hash_node)
        input_nodes = form.xpath('.//input[contains(@name, "email_")]')
        form_values = {
            input_node.attrib["name"]: input_node for input_node in input_nodes
        }
        if "email_to" not in form_values:
            continue

        email_to_value = form_values["email_to"].attrib.get("value")
        if not email_to_value or (
            email_to_value == "info@yourcompany.example.com"
            and html_fragment.xpath('//span[@data-for="contactus_form"]')
        ):
            email_to_value = env_sudo.company.email or ""

        extra_recipients = {
            name: form_values[name].attrib.get("value") or ""
            for name in ("email_cc", "email_bcc")
            if name in form_values
        }
        value = website_form_signature_payload(email_to_value, extra_recipients)
        hash_value = hmac(env_sudo, "website_form_signature", value)
        hash_node = etree.Element(
            "input",
            attrib={
                "type": "hidden",
                "value": hash_value,
                "class": "form-control s_website_form_input s_website_form_custom",
                "name": "website_form_signature",
            },
        )
        form_values["email_to"].addnext(hash_node)


def create_image_attachment(env, image_path, image_name):
    Attachments = env["ir.attachment"]
    return Attachments.create(
        {
            "public": True,
            "name": image_name,
            "type": "url",
            "url": Attachments.get_base_url() + image_path,
        }
    )
