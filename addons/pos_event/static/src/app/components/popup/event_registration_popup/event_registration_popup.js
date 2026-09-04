/** @odoo-module native */
import { AlertDialog, Dialog } from "@web/ui/dialog";
import { useService } from "@web/core/utils/hooks";
import { Component, useState } from "@odoo/owl";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { isValidEmail, looksLikePhoneNumber } from "@point_of_sale/utils";
import { ProductCard } from "@point_of_sale/app/components/product_card/product_card";
import { NumericInput } from "@point_of_sale/app/components/inputs/numeric_input/numeric_input";

export class EventRegistrationPopup extends Component {
    static template = "pos_event.EventRegistrationPopup";
    static props = ["data", "getPayload", "close", "event"];
    static components = {
        Dialog,
        ProductCard,
        NumericInput,
    };
    setup() {
        this.pos = usePos();
        this.dialog = useService("dialog");
        this.state = useState({
            byRegistration: [],
            byOrder: {},
            touchedFields: new Set(),
        });
        this.dataInQty = this.props.data.reduce((acc, data) => {
            for (let i = 0; i < data.qty; i++) {
                acc.push(data);
            }
            return acc;
        }, []);

        for (const [idx, data] of Object.entries(this.dataInQty)) {
            this.state.byRegistration[idx] = {
                ticket_id: data.ticket_id,
                product_id: data.product_id,
                questions: {},
            };

            for (const question of this.questionsByRegistration) {
                this.state.byRegistration[idx].questions[question.id] = "";
            }
        }

        for (const question of this.questionsOncePerOrder) {
            this.state.byOrder[question.id] = "";
        }

        if (this.props.event.question_ids.length === 0) {
            this.confirm();
        }
    }

    get questionsByRegistration() {
        return this.props.event.question_ids.filter(
            (question) => !question.once_per_order,
        );
    }

    get questionsOncePerOrder() {
        return this.props.event.question_ids.filter(
            (question) => question.once_per_order,
        );
    }

    _fieldKey(questionId, ticketIndex = null) {
        return ticketIndex === null
            ? `order:${questionId}`
            : `registration:${ticketIndex}:${questionId}`;
    }

    markTouched(questionId, ticketIndex = null) {
        this.state.touchedFields.add(this._fieldKey(questionId, ticketIndex));
    }

    isAnswerValid(question, value) {
        if (question.is_mandatory_answer && !value?.trim()) {
            return false;
        }
        if (!value) {
            return true;
        }
        if (question.question_type === "email") {
            return Boolean(isValidEmail(value));
        }
        if (question.question_type === "phone") {
            return looksLikePhoneNumber(value);
        }
        return true;
    }

    /** Only flag a field the cashier has already left, not one being typed. */
    answerClass(question, answers, ticketIndex = null) {
        const touched = this.state.touchedFields.has(
            this._fieldKey(question.id, ticketIndex),
        );
        return touched && !this.isAnswerValid(question, answers[question.id])
            ? "border border-danger"
            : "";
    }

    get isConfirmable() {
        const allValid = (questions, answers) =>
            questions.every((question) => this.isAnswerValid(question, answers[question.id]));

        return (
            allValid(this.questionsOncePerOrder, this.state.byOrder) &&
            this.state.byRegistration.every((registration) =>
                allValid(this.questionsByRegistration, registration.questions),
            )
        );
    }

    isQuestionMissingMandatoryAnswer(id, value) {
        const question = this.pos.models["event.question"].get(id);
        return !!(question && question.is_mandatory_answer && !value);
    }

    confirm() {
        const requiredByRegistration = Object.values(this.state.byRegistration).some(
            (data) => {
                for (const [id, value] of Object.entries(data.questions)) {
                    if (this.isQuestionMissingMandatoryAnswer(id, value)) {
                        return true;
                    }
                }
            },
        );

        const requiredByOrder = Object.entries(this.state.byOrder).some(([id, value]) =>
            this.isQuestionMissingMandatoryAnswer(id, value),
        );

        if (requiredByRegistration || requiredByOrder) {
            this.dialog.add(AlertDialog, {
                title: "Error",
                body: "Please fill in all required fields",
            });
            return;
        }

        const registrationByTickets = this.state.byRegistration.reduce((acc, data) => {
            if (!acc[data.ticket_id.id]) {
                acc[data.ticket_id.id] = [];
            }

            acc[data.ticket_id.id].push(data.questions);
            return acc;
        }, {});

        this.props.getPayload({
            byRegistration: registrationByTickets,
            byOrder: this.state.byOrder,
        });
        this.props.close();
    }
    close() {
        this.props.close();
    }
}
