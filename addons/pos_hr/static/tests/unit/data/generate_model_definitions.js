// Side-effect prototype patches (base mock-model methods the pos_hr fields
// need); safe at import time since they only extend an already-defined
// prototype, unlike the record augmentation which must run post-registration.
import "./pos_order.data.js";
import "./pos_payment.data.js";
import "./pos_session.data.js";

import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";

import { HrEmployee } from "./hr_employee.data.js";
import { applyHrConfigRecords } from "./pos_config.data.js";

/**
 * Registers the base POS mock models plus the pos_hr-specific ones and
 * augments the config records. Every pos_hr HOOT unit test must call this
 * instead of the base definePosModels — otherwise the hr.employee model and
 * the employee_id fields the active pos_hr production patches read are absent,
 * and pos_data crashes at setup.
 */
export const definePosHrModels = () => {
    definePosModels([HrEmployee]);
    applyHrConfigRecords();
};
