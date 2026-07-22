# Part of Odoo. See LICENSE file for full copyright and licensing details.

import base64
import logging
import re
from urllib.parse import quote, urlsplit

import requests

from odoo import api, models
from odoo.libs.constants import DOTTED_ASSET_EXTENSIONS as EXTENSIONS
from odoo.tools import misc

_logger = logging.getLogger(__name__)

_match_asset_file_url_regex = re.compile(r"^(/_custom/([^/]+))?/(\w+)/([/\w]+\.\w+)$")

# Bounds/validation for the (untrusted, remote) Google Fonts fetch triggered
# when a designer localises a font. Kept tight on purpose: the request runs
# inside the settings-save transaction and the bytes are stored as *public*
# attachments, so a slow/oversized/mistyped response must not stall the worker
# or land arbitrary content on the site.
_GOOGLE_FONT_TIMEOUT = 5
_MAX_GOOGLE_FONTS = 20
_MAX_GOOGLE_FONT_SOURCES = 40
_MAX_GOOGLE_FONT_BYTES = 5 * 1024 * 1024
_GOOGLE_FONT_HEADERS = {
    # Google serves the format based on the UA; this one gets the woff2 variant
    # that every supported browser accepts.
    "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.41 Safari/537.36",
}


class WebsiteAssets(models.AbstractModel):
    _name = "website.assets"
    _description = "Assets Utils"

    @api.model
    def reset_asset(self, url, bundle):
        """Delete any customizations made to a given original asset.

        :param str url: the URL of the original asset (scss / js) file
        :param str bundle: the name of the bundle in which the customizations
            to delete were made
        """
        custom_url = self._make_custom_asset_url(url, bundle)

        # Delete both the attachment holding the modified scss/js file and the
        # ir.asset record which links it.
        self._get_custom_attachment(custom_url).unlink()
        self._get_custom_asset(custom_url).unlink()

    @api.model
    def save_asset(self, url, bundle, content, file_type):
        """Customize the content of a given asset (scss / js).

        :param str url: the URL of the original asset to customize (whether or
            not the asset was already customized)
        :param str bundle: the name of the bundle in which the customizations
            will take effect
        :param str content: the new content of the asset (scss / js)
        :param str file_type: either 'scss' or 'js' according to the file being
            customized
        """
        custom_url = self._make_custom_asset_url(url, bundle)
        datas = base64.b64encode((content or "\n").encode("utf-8"))

        # Check if the file to save had already been modified
        custom_attachment = self._get_custom_attachment(custom_url)
        if custom_attachment:
            # If it was already modified, simply override the corresponding
            # attachment content
            custom_attachment.write({"datas": datas})
            self.env.registry.clear_cache("assets")
        else:
            # If not, create a new attachment to copy the original scss/js file
            # content, with its modifications
            new_attach = {
                "name": url.split("/")[-1],
                "type": "binary",
                "mimetype": ((file_type == "js" and "text/javascript") or "text/scss"),
                "datas": datas,
                "url": custom_url,
                **self._add_website_id({}),
            }
            self.env["ir.attachment"].create(new_attach)

            # Create an asset with the new attachment
            IrAsset = self.env["ir.asset"]
            new_asset = {
                "path": custom_url,
                "target": url,
                "directive": "replace",
                **self._add_website_id({}),
            }
            target_asset = self._get_custom_asset(url)
            if target_asset:
                new_asset["name"] = target_asset.name + " override"
                new_asset["bundle"] = target_asset.bundle
                new_asset["sequence"] = target_asset.sequence
            else:
                new_asset["name"] = "%s: replace %s" % (
                    bundle,
                    custom_url.split("/")[-1],
                )
                new_asset["bundle"] = IrAsset._get_related_bundle(url, bundle)
            IrAsset.create(new_asset)

    @api.model
    def _get_content_from_url(self, url, url_info=None, custom_attachments=None):
        """Fetch the content of an asset (scss / js) file.

        The content comes either from the related file on disk or from the
        corresponding custom ir.attachment record.

        :param str url: the URL of the asset (scss / js) file/ir.attachment
        :param dict url_info: (optional) the related url info (see
            _get_data_from_url); lets a caller that already has it avoid
            re-fetching
        :param custom_attachments: (optional) the related custom ir.attachment
            records to search into; lets a caller that already has them avoid
            re-fetching
        :return: the raw bytes of the asset content, or False if a customized
            attachment is missing
        :rtype: bytes
        """
        if url_info is None:
            url_info = self._get_data_from_url(url)

        if url_info["customized"]:
            # If the file is already customized, the content is found in the
            # corresponding attachment
            attachment = None
            if custom_attachments is None:
                attachment = self._get_custom_attachment(url)
            else:
                attachment = custom_attachments.filtered(lambda r: r.url == url)
            return (attachment and base64.b64decode(attachment.datas)) or False

        # If the file is not yet customized, the content is found by reading
        # the local file
        with misc.file_open(url.strip("/"), "rb", filter_ext=EXTENSIONS) as f:
            return f.read()

    @api.model
    def _get_data_from_url(self, url):
        """Return information about an asset (scss / js) file/ir.attachment
        inferred from its URL alone.

        :param str url: the url of the asset (scss / js) file/ir.attachment
        :return: a dict with keys ``module`` (the original asset's related
            app), ``resource_path`` (the relative path to the original asset
            from the related app), ``customized`` (whether the asset is a
            customized one), and ``bundle`` (the name of the bundle the asset
            customizes, False if not a customized asset); False when the URL
            does not match an asset
        :rtype: dict
        """
        m = _match_asset_file_url_regex.match(url)
        if not m:
            return False
        return {
            "module": m.group(3),
            "resource_path": m.group(4),
            "customized": bool(m.group(1)),
            "bundle": m.group(2) or False,
        }

    @api.model
    def _make_custom_asset_url(self, url, bundle_xmlid):
        """Return the URL a given asset would have if it were customized.

        :param str url: the original asset's url
        :param str bundle_xmlid: the name of the bundle the asset would customize
        :return: the URL the given asset would have if customized in the given
            bundle
        :rtype: str
        """
        return f"/_custom/{bundle_xmlid}{url}"

    @api.model
    def make_scss_customization(self, url, values):
        """Customize the given scss file.

        The file must contain a scss map including a line comment containing the
        word 'hook', which marks where to write the new key,value pairs.

        :param str url: the URL of the scss file to customize (expected to be a
            variable file appearing in the assets_frontend bundle)
        :param dict values: key,value mapping to integrate in the file's map. If
            a key is already present, its value is overridden.
        """
        IrAttachment = self.env["ir.attachment"]
        if "color-palettes-name" in values:
            self.reset_asset(
                "/website/static/src/scss/options/colors/user_color_palette.scss",
                "web.assets_frontend",
            )
            self.reset_asset(
                "/website/static/src/scss/options/colors/user_gray_color_palette.scss",
                "web.assets_frontend",
            )
            # Do not reset all theme colors for compatibility (not removing alpha -> epsilon colors)
            self.make_scss_customization(
                "/website/static/src/scss/options/colors/user_theme_color_palette.scss",
                {
                    "success": "null",
                    "info": "null",
                    "warning": "null",
                    "danger": "null",
                },
            )
            # Also reset gradients which are in the "website" values palette
            preset_gradients = {f"o-cc{cc}-bg-gradient": "null" for cc in range(1, 6)}
            self.make_scss_customization(
                "/website/static/src/scss/options/user_values.scss",
                {
                    "menu-gradient": "null",
                    "menu-secondary-gradient": "null",
                    "footer-gradient": "null",
                    "copyright-gradient": "null",
                    **preset_gradients,
                },
            )

        delete_attachment_id = values.pop("delete-font-attachment-id", None)
        if delete_attachment_id:
            delete_attachment_id = int(delete_attachment_id)
            IrAttachment.search(
                [
                    "|",
                    ("id", "=", delete_attachment_id),
                    ("original_id", "=", delete_attachment_id),
                    ("name", "like", "google-font"),
                ]
            ).unlink()

        google_local_fonts = values.get("google-local-fonts")
        if google_local_fonts and google_local_fonts != "null":
            # "('font_x': 45, 'font_y': '')" -> {'font_x': '45', 'font_y': ''}
            google_local_fonts = dict(
                re.findall(r"'([^']+)': '?(\d*)", google_local_fonts)
            )
            google_local_fonts = self._localize_google_fonts(google_local_fonts)
            # {'font_x': 45, 'font_y': 55} -> "('font_x': 45, 'font_y': 55)"
            values["google-local-fonts"] = (
                str(google_local_fonts).replace("{", "(").replace("}", ")")
            )

        custom_url = self._make_custom_asset_url(url, "web.assets_frontend")
        updatedFileContent = self._get_content_from_url(
            custom_url
        ) or self._get_content_from_url(url)
        updatedFileContent = updatedFileContent.decode("utf-8")
        for name, value in values.items():
            # Protect variable names so they cannot be computed as numbers
            # on SCSS compilation (e.g. var(--700) => var(700)).
            if isinstance(value, str):
                value = re.sub(
                    r"var\(--([0-9]+)\)",
                    lambda matchobj: "var(--#{" + matchobj.group(1) + "})",
                    value,
                )
            pattern = "'%s': %%s,\n" % name
            regex = re.compile(pattern % ".+")
            replacement = pattern % value
            if regex.search(updatedFileContent):
                updatedFileContent = re.sub(regex, replacement, updatedFileContent)
            else:
                updatedFileContent = re.sub(
                    r"^( *)(.*hook.*)",
                    r"\1%s\1\2" % replacement,
                    updatedFileContent,
                    count=1,
                    flags=re.MULTILINE,
                )

        self.save_asset(url, "web.assets_frontend", updatedFileContent, "scss")

    def _localize_google_fonts(self, google_local_fonts):
        """Resolve a ``{font_name: size_or_empty}`` map to ``{font_name: id}``.

        A font already localised keeps its stored attachment id; a font with no
        id is fetched from Google (CSS + woff2 files) and stored as attachments.
        The number of families fetched per save is bounded, and a family that
        cannot be fetched is dropped from the map (it falls back to the online
        Google font) rather than aborting the whole settings save.
        """
        resolved = {}
        fetched = 0
        for font_name, size in google_local_fonts.items():
            if size:
                resolved[font_name] = int(size)
                continue
            if fetched >= _MAX_GOOGLE_FONTS:
                _logger.warning(
                    "Refusing to fetch more than %s Google fonts in one save; "
                    "%r left online.",
                    _MAX_GOOGLE_FONTS,
                    font_name,
                )
                continue
            fetched += 1
            attachment_id = self._fetch_google_local_font(font_name)
            if attachment_id:
                resolved[font_name] = attachment_id
            else:
                _logger.warning(
                    "Could not localise Google font %r; leaving it online.",
                    font_name,
                )
        return resolved

    def _fetch_google_local_font(self, font_name):
        """Fetch a Google font family (CSS + woff2 files) and store attachments.

        Returns the id of the main CSS attachment, or ``None`` if the family's
        stylesheet could not be fetched.
        """
        IrAttachment = self.env["ir.attachment"]
        css = self._http_get_google_font(
            f"https://fonts.googleapis.com/css?family={quote(font_name)}"
            ":300,300i,400,400i,700,700i&display=swap",
            expect_binary=False,
        )
        if css is None:
            return None
        font_content = css.decode()

        font_family_attachments = IrAttachment
        source_count = 0

        def replace_src(match):
            nonlocal source_count, font_family_attachments
            statement = match.group()
            m = re.match(r"src: url\(([^\)]+)\) (.+)", statement)
            if not m:
                # Google changed its @font-face CSS shape: leave the statement
                # untouched instead of crashing on ``None.groups()``.
                return statement
            if source_count >= _MAX_GOOGLE_FONT_SOURCES:
                _logger.warning(
                    "Google font %r exposes more than %s sources; truncating.",
                    font_name,
                    _MAX_GOOGLE_FONT_SOURCES,
                )
                return statement
            source_count += 1
            url, font_format = m.groups()
            content = self._http_get_google_font(url, expect_binary=True)
            if content is None:
                # Keep the remote URL rather than mint a broken local one.
                return statement
            # https://fonts.gstatic.com/s/modak/v18/EJRYQgs1XtIEskMB-hRp7w.woff2
            # -> s-modak-v18-EJRYQgs1XtIEskMB-hRp7w.woff2
            name = urlsplit(url).path.lstrip("/").replace("/", "-")
            attachment = IrAttachment.create(
                {
                    "name": f"google-font-{name}",
                    "type": "binary",
                    "datas": base64.b64encode(content),
                    "public": True,
                }
            )
            font_family_attachments += attachment
            return "src: url(/web/content/%s/%s) %s" % (
                attachment.id,
                name,
                font_format,
            )

        font_content = re.sub(r"src: url\(.+\)", replace_src, font_content)
        attach_font = IrAttachment.create(
            {
                "name": f"{font_name} (google-font)",
                "type": "binary",
                "datas": base64.encodebytes(font_content.encode()),
                "mimetype": "text/css",
                "public": True,
            }
        )
        # ``original_id`` normally tracks the origin of a modified image; reuse
        # it here to link the family's binaries to the main CSS attachment, which
        # eases their unlink later.
        if font_family_attachments:
            font_family_attachments.original_id = attach_font.id
        return attach_font.id

    def _http_get_google_font(self, url, *, expect_binary):
        """GET a Google Fonts resource with a timeout, size cap and validation.

        Returns the response bytes, or ``None`` when the request fails, is too
        large, or (for a binary) is not served as a font — so the caller never
        stores arbitrary remote bytes as a public attachment.
        """
        try:
            with requests.get(
                url,
                timeout=_GOOGLE_FONT_TIMEOUT,
                headers=_GOOGLE_FONT_HEADERS,
                stream=True,
            ) as response:
                response.raise_for_status()
                if expect_binary:
                    content_type = response.headers.get("content-type", "").lower()
                    if not any(
                        token in content_type
                        for token in ("font", "woff", "octet-stream")
                    ):
                        _logger.warning(
                            "Unexpected content-type %r for Google font %s",
                            content_type,
                            url,
                        )
                        return None
                chunks = []
                total = 0
                for chunk in response.iter_content(64 * 1024):
                    total += len(chunk)
                    if total > _MAX_GOOGLE_FONT_BYTES:
                        _logger.warning(
                            "Google Fonts resource exceeds %s bytes: %s",
                            _MAX_GOOGLE_FONT_BYTES,
                            url,
                        )
                        return None
                    chunks.append(chunk)
                return b"".join(chunks)
        except requests.RequestException:
            _logger.warning("Google Fonts request failed: %s", url)
            return None

    @api.model
    def _get_custom_attachment(self, custom_url, op="="):
        """Fetch the ir.attachment record related to the given customized asset.

        Only attachments related to the current website are returned.

        :param str custom_url: the URL of the customized asset
        :param str op: the operator used to search the records ('in' or '=')
        :return: the matching attachment(s)
        :rtype: ir.attachment
        """
        assert op in ("in", "="), "Invalid operator"
        if self.env.user.has_group("website.group_website_designer"):
            self = self.sudo()
        website = self.env["website"].get_current_website()
        res = self.env["ir.attachment"].search([("url", op, custom_url)])
        # It is guaranteed that the attachment we are looking for has a website_id.
        # When we serve an attachment we normally serve the ones which have the right website_id
        # or no website_id at all (which means "available to all websites", of
        # course if they are marked "public"). But this does not apply in this
        # case of customized asset files.
        return res.with_context(website_id=website.id).filtered(
            lambda x: x.website_id == website
        )

    @api.model
    def _get_custom_asset(self, custom_url):
        """Fetch the ir.asset record related to the given customized asset.

        The asset is the ``replace`` directive that swaps the original asset for
        the customized one. Only assets related to the current website are
        returned.

        :param str custom_url: the URL of the customized asset
        :return: the matching asset record(s)
        :rtype: ir.asset
        """
        website = self.env["website"].get_current_website()
        url = custom_url[1:] if custom_url.startswith(("/", "\\")) else custom_url
        res = self.env["ir.asset"].search([("path", "like", url)])
        return res.with_context(website_id=website.id).filter_duplicate()

    @api.model
    def _add_website_id(self, values):
        website = self.env["website"].get_current_website()
        values["website_id"] = website.id
        return values
