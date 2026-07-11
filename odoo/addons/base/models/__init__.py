# --- Assets ---
from . import assetsbundle

# --- Core metadata (ir.model) ---
from . import ir_model_common
from . import ir_model
from . import ir_model_fields
from . import ir_model_fields_selection
from . import ir_model_reflection
from . import ir_model_access
from . import ir_model_data
from . import ir_sequence

# --- UI: views, menus, assets ---
from . import ir_ui_menu
from . import ir_ui_view_custom
from . import ir_ui_view
from . import ir_ui_view_base
from . import ir_ui_view_name_manager
from . import ir_asset

# --- Actions ---
from . import ir_actions
from . import ir_actions_server
from . import ir_embedded_actions
from . import ir_actions_report

# --- Storage ---
from . import ir_attachment_storage
from . import ir_attachment
from . import ir_attachment_assets
from . import ir_binary

# --- Scheduling ---
from . import ir_cron
from . import ir_job  # imports from ir_cron; must follow it
from . import ir_autovacuum

# --- Filters, defaults, exports ---
from . import ir_filters
from . import ir_default
from . import ir_exports
from . import ir_rule
from . import ir_config_parameter

# --- Mail ---
from . import ir_mail_server

# --- Import converters ---
from . import ir_fields

# --- Templating (QWeb) ---
from . import ir_qweb
from . import ir_qweb_assets
from . import ir_qweb_fields

# --- HTTP & logging ---
from . import ir_http
from . import ir_logging

# --- Modules ---
from . import ir_module
from . import ir_demo
from . import ir_demo_failure

# --- Properties & reports ---
from . import properties_base_definition
from . import properties_base_definition_mixin
from . import report_layout
from . import report_paperformat

# --- Profiling & mixins ---
from . import ir_profile
from . import image_mixin
from . import avatar_mixin
from . import tag_mixin
from . import tag_tag

# --- Partner ---
from . import res_partner_format_vat_mixin
from . import res_partner_format_address_mixin
from . import res_partner_category
from . import res_partner_industry
from . import res_country
from . import res_lang
from . import res_partner

# --- Banking & currency ---
from . import res_bank
from . import res_config
from . import res_currency
from . import res_company

# --- Users & groups ---
from . import res_groups_privilege
from . import res_groups
from . import res_users_log
from . import res_users
from . import res_users_identitycheck
from . import res_users_apikeys
from . import res_users_settings
from . import res_users_deletion
from . import res_device

# --- Precision ---
from . import decimal_precision

# --- Misc ---
from . import kpi_provider
