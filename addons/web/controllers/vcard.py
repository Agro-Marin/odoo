import importlib.util
import io
import zipfile

from odoo import _, http
from odoo.exceptions import UserError
from odoo.http import content_disposition, request
from odoo.libs.filesystem import osutil


class Partner(http.Controller):
    @http.route(
        [
            '/web_enterprise/partner/<model("res.partner"):partner>/vcard',
            "/web/partner/vcard",
        ],
        type="http",
        auth="user",
    )
    def download_vcard(self, partner_ids=None, partner=None, **kwargs):
        if importlib.util.find_spec("vobject") is None:
            raise UserError(_("vobject library is not installed"))

        partners = request.env["res.partner"]
        if partner_ids:
            partner_ids = [
                int(pid)
                for pid in partner_ids.split(",")
                if pid.isdigit() and pid != "0"
            ]
            partners = request.env["res.partner"].browse(partner_ids)
            if len(partners) > 1:
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w") as zipf:
                    used_names = set()
                    for p in partners:
                        label = p.name or p.email or f"contact_{p.id}"
                        # Sanitize: a partner named e.g. "../../../evil" would
                        # otherwise write a traversing zip entry (zip-slip against
                        # a non-hardening extractor). De-duplicate too: two
                        # partners sharing a name collide into one entry, which
                        # zipfile silently keeps the last of — dropping records.
                        name = osutil.clean_filename(f"{label}.vcf")
                        candidate, i = name, 1
                        while candidate in used_names:
                            candidate = osutil.clean_filename(f"{label} ({i}).vcf")
                            i += 1
                        used_names.add(candidate)
                        zipf.writestr(candidate, p._get_vcard_file())
                zip_data = buffer.getvalue()
                return request.make_response(
                    zip_data,
                    [
                        ("Content-Type", "application/zip"),
                        ("Content-Length", len(zip_data)),
                        (
                            "Content-Disposition",
                            content_disposition("Contacts.zip"),
                        ),
                    ],
                )

        if partner or partners:
            partner = partner or partners
            content = partner._get_vcard_file()
            return request.make_response(
                content,
                [
                    ("Content-Type", "text/vcard"),
                    ("Content-Length", len(content)),
                    (
                        "Content-Disposition",
                        content_disposition(
                            f"{partner.name or partner.email or f'contact_{partner.id}'}.vcf"
                        ),
                    ),
                ],
            )

        return request.not_found()
