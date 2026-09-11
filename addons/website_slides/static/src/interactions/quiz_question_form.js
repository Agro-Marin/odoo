/** @odoo-module native */
import { rpc } from "@web/core/network";
import { _t } from "@web/core/translation";
import { renderToElement } from "@web/core/utils/render";

export class QuestionFormBehavior {
    /**
     * @param {import("@web/public/interaction").Interaction} host
     * @param {HTMLElement} targetEl
     * @param {"beforeend"|"afterend"} position
     * @param {Object} options
     * @param {HTMLElement} [options.editedQuestionEl]
     * @param {Object} [options.question]
     * @param {boolean} [options.update]
     * @param {integer} options.sequence
     * @param {integer} options.slideId
     * @param {Function} options.onDisplayCreated
     * @param {Function} options.onDisplayUpdated
     * @param {Function} options.onResetDisplay
     */
    constructor(host, targetEl, position, options) {
        this.host = host;
        this.editedQuestionEl = options.editedQuestionEl;
        this.question = options.question || {};
        this.update = options.update;
        this.sequence = options.sequence;
        this.slideId = options.slideId;
        this.onDisplayCreated = options.onDisplayCreated;
        this.onDisplayUpdated = options.onDisplayUpdated;
        this.onResetDisplay = options.onResetDisplay;

        [this.el] = host.renderAt(
            "slide.quiz.question.input",
            { widget: this },
            targetEl,
            position,
        );

        const handlers = {
            ".o_wslides_js_quiz_validate_question": this._validateQuestion,
            ".o_wslides_js_quiz_cancel_question": this._cancelValidation,
            ".o_wslides_js_quiz_comment_answer": this._toggleAnswerLineComment,
            ".o_wslides_js_quiz_add_answer": this._addAnswerLine,
            ".o_wslides_js_quiz_remove_answer": this._removeAnswerLine,
            ".o_wslides_js_quiz_remove_answer_comment": this._removeAnswerLineComment,
        };
        host.addListener(this.el, "click", (ev) => {
            for (const [selector, handler] of Object.entries(handlers)) {
                const target = ev.target.closest(selector);
                if (target && this.el.contains(target)) {
                    handler.call(this, ev, target);
                    return;
                }
            }
        });
        host.addListener(this.el, "change", (ev) => {
            if (
                ev.target.matches(
                    ".o_wslides_js_quiz_answer_comment > input[type=text]",
                )
            ) {
                this._onCommentChanged(ev);
            }
        });

        const input = this.el.querySelector(".o_wslides_quiz_question input");
        if (input) {
            input.focus();
        }
    }

    destroy() {
        this.el.remove();
    }

    /**
     * @param {Event} ev
     */
    _onCommentChanged(ev) {
        const input = ev.target;
        const commentIcon = input
            .closest(".o_wslides_js_quiz_answer")
            .querySelector(".o_wslides_js_quiz_comment_answer");
        if (input.value.trim() !== "") {
            commentIcon.classList.add("text-primary");
            commentIcon.classList.remove("text-muted");
        } else {
            commentIcon.classList.add("text-muted");
            commentIcon.classList.remove("text-primary");
        }
    }

    /**
     * @param {Event} ev
     * @param {HTMLElement} target
     */
    _toggleAnswerLineComment(ev, target) {
        const answerEl = target.closest(".o_wslides_js_quiz_answer");
        const commentLine = answerEl.querySelector(".o_wslides_js_quiz_answer_comment");
        commentLine.classList.toggle("d-none");
        const input = commentLine.querySelector("input[type=text]");
        if (input) {
            input.focus();
        }
    }

    /**
     * @param {Event} ev
     * @param {HTMLElement} target
     */
    _addAnswerLine(ev, target) {
        target
            .closest(".o_wslides_js_quiz_answer")
            .after(renderToElement("slide.quiz.answer.line"));
    }

    /**
     * @param {Event} ev
     * @param {HTMLElement} target
     */
    _removeAnswerLine(ev, target) {
        if (this.el.querySelectorAll(".o_wslides_js_quiz_answer").length > 1) {
            target.closest(".o_wslides_js_quiz_answer").remove();
        }
    }

    /**
     * @param {Event} ev
     * @param {HTMLElement} target
     */
    _removeAnswerLineComment(ev, target) {
        const commentLine = target.closest(".o_wslides_js_quiz_answer_comment");
        commentLine.classList.add("d-none");
        const input = commentLine.querySelector("input[type=text]");
        input.value = "";
        input.dispatchEvent(new Event("change", { bubbles: true }));
    }

    /**
     * @param {Event} ev
     * @param {HTMLElement} target
     */
    _validateQuestion(ev, target) {
        this._createOrUpdateQuestion({
            update: target.classList.contains("o_wslides_js_quiz_update"),
        });
    }

    _cancelValidation() {
        this.onResetDisplay(this);
    }

    /**
     * @param {Object} options
     */
    async _createOrUpdateQuestion(options) {
        const form = this.el.querySelector("form");
        const errorContainer = this.el.querySelector(
            ".o_wslides_js_quiz_validation_error",
        );

        if (this._isValidForm(form)) {
            const values = this._serializeForm(form);
            const renderedQuestion = await this.host.waitFor(
                rpc("/slides/slide/quiz/question_add_or_update", values),
            );

            if (typeof renderedQuestion === "object" && renderedQuestion.error) {
                errorContainer.classList.remove("d-none");
                errorContainer.querySelector(
                    ".o_wslides_js_quiz_validation_error_text",
                ).textContent = renderedQuestion.error;
            } else if (options.update) {
                errorContainer.classList.add("d-none");
                this.onDisplayUpdated(this, renderedQuestion, this.editedQuestionEl);
            } else {
                errorContainer.classList.add("d-none");
                this.onDisplayCreated(this, renderedQuestion);
            }
        } else {
            errorContainer.classList.remove("d-none");
            errorContainer.querySelector(
                ".o_wslides_js_quiz_validation_error_text",
            ).textContent = _t("Please fill in the question");
            const input = this.el.querySelector(".o_wslides_quiz_question input");
            if (input) {
                input.focus();
            }
        }
    }

    /**
     * @param {HTMLFormElement} form
     * @returns {boolean}
     */
    _isValidForm(form) {
        return (
            form
                .querySelector(".o_wslides_quiz_question input[type=text]")
                .value.trim() !== ""
        );
    }

    /**
     * @param {HTMLFormElement} form
     * @returns {{existing_question_id: *, sequence: *, question: *, slide_id: *, answer_ids: Array}}
     */
    _serializeForm(form) {
        const answers = [];
        let sequence = 1;
        for (const answerEl of form.querySelectorAll(".o_wslides_js_quiz_answer")) {
            const value = answerEl.querySelector(
                ".o_wslides_js_quiz_answer_value",
            ).value;
            if (value.trim() !== "") {
                answers.push({
                    sequence: sequence++,
                    text_value: value,
                    is_correct: answerEl.querySelector("input[type=radio]").checked,
                    comment:
                        answerEl
                            .querySelector(
                                ".o_wslides_js_quiz_answer_comment input[type=text]",
                            )
                            ?.value?.trim() || "",
                });
            }
        }
        return {
            existing_question_id: this.el.dataset.id,
            sequence: this.sequence,
            question: form.querySelector(".o_wslides_quiz_question input[type=text]")
                .value,
            slide_id: this.slideId,
            answer_ids: answers,
        };
    }
}
