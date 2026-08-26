import { beforeEach } from "@odoo/hoot";
import { definePosModels } from "@point_of_sale/../tests/unit/data/generate_model_definitions";

import { EventEvent } from "./event_event.data.js";
import { EventEventTicket } from "./event_event_ticket.data.js";
import { EventQuestion } from "./event_question.data.js";
import { EventQuestionAnswer } from "./event_question_answer.data.js";
import { EventRegistration } from "./event_registration.data.js";
import { EventRegistrationAnswer } from "./event_registration_answer.data.js";
import { EventSlot } from "./event_slot.data.js";
import { applyEventProductProductRecords } from "./product_product.data.js";
import { applyEventProductTemplateRecords } from "./product_template.data.js";

/**
 * Registers the base POS mock models plus pos_event's own, and applies its
 * record fixtures.
 *
 * Every pos_event HOOT unit test must call this instead of the base
 * definePosModels. The record patches are applied per test via `beforeEach`,
 * NOT at module-eval time: hoot imports every test file in the unit-test
 * bundle during collection, so an eager mutation of a shared model definition
 * both fails to reach this addon's own mock server and leaks into every other
 * POS suite. `beforeEach` (not `before`) is required -- model definitions are
 * job-scoped per test, so a suite-level hook mutates the parent job's
 * definition.
 */
export const definePosEventModels = (extraModels = []) => {
    definePosModels([
        EventEvent,
        EventEventTicket,
        EventQuestion,
        EventQuestionAnswer,
        EventRegistration,
        EventRegistrationAnswer,
        EventSlot,
        ...extraModels,
    ]);
    beforeEach(applyEventProductProductRecords);
    beforeEach(applyEventProductTemplateRecords);
};
