# mixin
from . import mixin_documents_unlink
from . import mixin_documents

# documents
from . import documents_access
from . import documents_access_log
from . import documents_access_tracking
from . import documents_document

# Concerns of `documents.document`, in their own files. The base class (with
# `_name`) has to be registered first; each of these extends it with `_inherit`.
from . import documents_document_access
from . import documents_document_user_folder
from . import documents_document_search_panel
from . import documents_document_versioning
from . import documents_document_embedded_actions
from . import documents_document_mail
from . import documents_redirect
from . import documents_tag

# orm
from . import ir_attachment
from . import ir_binary
from . import ir_http

# inherit
from . import ir_actions_server
from . import ir_embedded_actions
from . import mail_activity
from . import mail_activity_type
from . import res_partner
from . import res_users
from . import res_company
from . import res_config_settings
