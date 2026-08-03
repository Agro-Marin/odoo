/** @odoo-module native */
import { GraphModel } from "@web/views/graph";

import { patchGraphModel } from "../graph_model_patch.js";

export class hrTimesheetGraphModel extends GraphModel {}
patchGraphModel(hrTimesheetGraphModel);
