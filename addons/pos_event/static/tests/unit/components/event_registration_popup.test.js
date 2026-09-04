import { expect, test } from "@odoo/hoot";
import { EventRegistrationPopup } from "@pos_event/app/components/popup/event_registration_popup/event_registration_popup";
import { mountPosDialog, setupPosEnv } from "@point_of_sale/../tests/unit/utils";
import { definePosEventModels } from "../data/generate_model_definitions.js";

definePosEventModels();

test("confirm payload", async () => {
    const store = await setupPosEnv();
    const event = store.models["event.event"].get(1);
    const tickets = [store.models["event.event.ticket"].get(1)];
    let payload = [];
    const data = [
        {
            qty: 1,
            ticket_id: tickets[0],
            product_id: tickets[0].product_id,
        },
    ];
    const comp = await mountPosDialog(EventRegistrationPopup, {
        event: event,
        data: data,
        getPayload: (data) => {
            payload = data;
        },
        close: () => {},
    });

    comp.state.byRegistration[0].questions = {
        1: "Test User",
        2: "test@test.com",
        3: "+911234567890",
        4: "1",
    };
    comp.confirm();

    const receivedValues = Object.values(payload.byRegistration[1][0]);
    expect(payload.byRegistration).toHaveLength(1);
    expect(parseInt(Object.keys(payload.byRegistration)[0])).toBe(tickets[0].id);
    expect(receivedValues).toEqual([
        "Test User",
        "test@test.com",
        "+911234567890",
        "1", // Received value is the ID of the answer `Male`, not the name.
    ]);
});

const mountRegistrationPopup = async (store) => {
    const tickets = [store.models["event.event.ticket"].get(1)];
    return mountPosDialog(EventRegistrationPopup, {
        event: store.models["event.event"].get(1),
        data: [{ qty: 1, ticket_id: tickets[0], product_id: tickets[0].product_id }],
        getPayload: () => {},
        close: () => {},
    });
};

test("Confirm stays out of reach until every answer is valid", async () => {
    const store = await setupPosEnv();
    const comp = await mountRegistrationPopup(store);
    const answers = comp.state.byRegistration[0].questions;

    // Name, Email and Phone are mandatory and still empty.
    expect(comp.isConfirmable).toBe(false);

    answers[1] = "Test User";
    answers[2] = "not-an-email";
    answers[3] = "+911234567890";
    expect(comp.isConfirmable).toBe(false);

    answers[2] = "test@test.com";
    expect(comp.isConfirmable).toBe(true);

    // Too short to be a phone number.
    answers[3] = "12";
    expect(comp.isConfirmable).toBe(false);

    answers[3] = "+91 (123) 456-7890";
    expect(comp.isConfirmable).toBe(true);
});

test("A field is only flagged once the cashier has left it", async () => {
    const store = await setupPosEnv();
    const comp = await mountRegistrationPopup(store);
    const answers = comp.state.byRegistration[0].questions;
    const email = store.models["event.question"].get(2);

    answers[2] = "not-an-email";
    expect(comp.answerClass(email, answers, 0)).toBe("");

    comp.markTouched(email.id, 0);
    expect(comp.answerClass(email, answers, 0)).toBe("border border-danger");

    answers[2] = "test@test.com";
    expect(comp.answerClass(email, answers, 0)).toBe("");
});
