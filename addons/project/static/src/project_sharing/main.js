/** @odoo-module native */
import { startWebClient } from "@web/boot/start";

import { ProjectSharingWebClient } from "./project_sharing.js";
import { removeServices } from "./remove_services.js";

removeServices();
startWebClient(ProjectSharingWebClient);
