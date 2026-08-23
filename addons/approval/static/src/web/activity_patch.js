/** @odoo-module native */
import { Activity } from "@mail/core/web/activity";

import { Approval } from "@approval/web/approval";

Object.assign(Activity.components, { Approval });
