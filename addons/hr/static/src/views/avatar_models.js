// @ts-check
/** @odoo-module native */

import { avatarModels } from "@web/components/record_selectors";

// Record selectors draw an avatar beside these. `web` used to name them in a
// literal it could not have maintained: it does not depend on `hr` and cannot know
// which of its models carry one.
avatarModels.add("hr.employee", true).add("hr.employee.public", true);
