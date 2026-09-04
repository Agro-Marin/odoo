=====
Cloud
=====

Cloud-only Drive/SharePoint on a **dedicated** S3 bucket.

Files live 100% in the bucket under their **original names/paths** — there is no
filestore copy and **no ``ir.attachment`` / ``documents.document`` row per file**.
The bucket is the source of truth; the UI lists it live with ``ListObjectsV2``,
uploads and downloads happen **browser-direct** through presigned URLs, and the
Odoo controller only acts as the access-control gate.

Access levels (global, 3 groups)
=================================

- **Read** — browse, view, download.
- **Upload + Read** — plus upload files, create folders, and rename/move/copy
  both files **and folders** (folder operations are recursive over every object
  under the folder's prefix). Move and copy **never overwrite**: an operation
  whose destination already exists is refused, so an upload user cannot destroy
  an existing file's current version (deletion stays admin-only). Re-uploading
  the same name *does* replace the object's current version — bucket versioning
  (see below) preserves the prior one.
- **Administrator** — plus delete files/folders and configure the Drive.

Credentials
===========

The bucket IAM keys are stored **encrypted** in ``credential``
(``credential.credential``, category ``drive_s3``), never in cleartext config
parameters. The bucket name and region (non-secret) live in system parameters.

Required IAM permissions
========================

``s3:PutObject``, ``s3:GetObject``, ``s3:DeleteObject``, ``s3:ListBucket``,
``s3:GetBucketVersioning`` (for the versioning check on **Test Connection**),
``s3:PutBucketCors`` (the last only to auto-configure CORS from Settings).

The bucket must have **versioning enabled** (overwrites keep the previous
version) and a CORS policy allowing the Odoo origin (``GET``, ``POST``).
**Test Connection** actively verifies versioning is enabled and refuses the
configuration otherwise, so the "overwrites never destroy the prior version"
guarantee is enforced rather than assumed. Uploads are browser-direct
**presigned POST**, whose signed ``content-length-range`` policy caps the object
size at S3 itself (a plain ``PUT`` cannot enforce a maximum), so the size limit
is not merely a client-side hint. The single-object cap is 5 GB, which is also
the S3 single-part copy limit, so move/copy of a 5 GB object stays within one
server-side ``CopyObject`` call.
