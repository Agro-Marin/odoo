/** @odoo-module native */
import { markup } from "@odoo/owl";
import { rpc } from "@web/core/network";
import { registry } from "@web/core/registry";
import { _t } from "@web/core/translation";
import { user } from "@web/core/user";
import { renderToElement } from "@web/core/utils/render";
import { session } from "@web/session";
import { ConfirmationDialog } from "@web/ui/dialog";
import { attachCourseJoin } from "@website_slides/interactions/course_join";
import { CoursePage } from "@website_slides/interactions/course_page";
import { QuestionFormBehavior } from "@website_slides/interactions/quiz_question_form";
import { SlideQuizFinishDialog } from "@website_slides/js/public/components/slide_quiz_finish_dialog/slide_quiz_finish_dialog";
import { parseQuestionMarkup } from "@website_slides/js/public/slides_course_utils";

export class QuizBehavior {
    /**
     * @param {import("@web/public/interaction").Interaction} host
     * @param {Object} params
     * @param {HTMLElement} [params.el]
     * @param {HTMLElement} [params.targetEl]
     * @param {Object} params.slideData
     * @param {Object} params.channelData
     * @param {Object} [params.quizData]
     * @returns {Promise<QuizBehavior>}
     */
    static async create(host, params) {
        let quizData = params.quizData;
        let sessionAnswers;
        if (!quizData) {
            const fetched = await host.waitFor(
                rpc("/slides/slide/quiz/get", { slide_id: params.slideData.id }),
            );
            sessionAnswers = fetched.session_answers;
            quizData = {
                description_safe: fetched.slide_description
                    ? markup(fetched.slide_description)
                    : "",
                questions: fetched.slide_questions || [],
                quizAttemptsCount: fetched.quiz_attempts_count || 0,
                quizKarmaGain: fetched.quiz_karma_gain || 0,
                quizKarmaWon: fetched.quiz_karma_won || 0,
                slideResources: fetched.slide_resource_ids || [],
            };
        }
        const quiz = new this(host, params, quizData);
        if (sessionAnswers !== undefined) {
            quiz.slide.sessionAnswers = sessionAnswers;
        }
        quiz.start();
        return quiz;
    }

    constructor(host, params, quizData) {
        this.host = host;
        this.slide = Object.assign(
            {
                id: 0,
                name: "",
                hasNext: false,
                completed: false,
                isMember: false,
                isMemberOrInvited: false,
            },
            params.slideData,
        );
        this.quiz = { ...quizData };
        this.quiz.questionsCount = (quizData.questions || []).length;
        this.isMember = this.slide.isMember || false;
        this.isMemberOrInvited = this.slide.isMemberOrInvited || false;
        this.publicUser = session.is_website_user;
        this.userId = user.userId;
        this.redirectURL = encodeURIComponent(document.URL);
        this.channel = params.channelData;

        this.eventRemovers = [];
        if (params.el) {
            this.el = params.el;
        } else {
            [this.el] = host.renderAt(
                "slide.slide.quiz",
                { widget: this },
                params.targetEl,
            );
        }
        this._bindEvents();
    }

    start() {
        this._renderValidationInfo();
        this._bindSortable();
        this._checkLocationHref();
        if (!this.isMember) {
            this._renderJoinWidget();
        } else if (this.slide.sessionAnswers) {
            this._applySessionAnswers();
            this._submitQuiz();
        }
    }

    rerender() {
        const newEl = renderToElement("slide.slide.quiz", { widget: this });
        this.el.replaceWith(newEl);
        this.el = newEl;
        this._bindEvents();
        this._bindSortable();
    }

    _bindEvents() {
        for (const remove of this.eventRemovers) {
            remove();
        }
        const handlers = {
            ".o_wslides_quiz_answer": this._onAnswerClick,
            ".o_wslides_js_lesson_quiz_submit": this._submitQuiz,
            ".o_wslides_quiz_continue": this._onClickNext,
            ".o_wslides_js_lesson_quiz_reset": this._onClickReset,
            ".o_wslides_js_quiz_add": this._onCreateQuizClick,
            ".o_wslides_js_quiz_edit_question": this._onEditQuestionClick,
            ".o_wslides_js_quiz_delete_question": this._onDeleteQuestionClick,
        };
        this.eventRemovers = [
            this.host.addListener(this.el, "click", (ev) => {
                for (const [selector, handler] of Object.entries(handlers)) {
                    const target = ev.target.closest(selector);
                    if (target && this.el.contains(target)) {
                        handler.call(this, ev, target);
                        return;
                    }
                }
            }),
        ];
    }

    _showErrorMessage(errorCode) {
        let message = _t("There was an error validating this quiz.");
        if (errorCode === "slide_quiz_incomplete") {
            message = _t("All questions must be answered!");
        } else if (errorCode === "slide_quiz_done") {
            message = _t("This quiz is already done. Retaking it is not possible.");
        } else if (errorCode === "public_user") {
            message = _t("You must be logged to submit the quiz.");
        }

        const errorEl = this.el.querySelector(".o_wslides_js_quiz_submit_error");
        if (errorEl) {
            errorEl.classList.remove("d-none");
            const textEl = errorEl.querySelector(
                ".o_wslides_js_quiz_submit_error_text",
            );
            if (textEl) {
                textEl.textContent = message;
            }
        }
    }

    _hideErrorMessage() {
        const errorEl = this.el.querySelector(".o_wslides_js_quiz_submit_error");
        if (errorEl) {
            errorEl.classList.add("d-none");
        }
    }

    _bindSortable() {
        this.bindedSortable?.cleanup();
        this.bindedSortable = this.host.services.sortable
            .create({
                ref: { el: this.el },
                handle: ".o_wslides_js_quiz_sequence_handler",
                elements: ".o_wslides_js_lesson_quiz_question",
                onDrop: this._reorderQuestions.bind(this),
                clone: false,
                placeholderClasses: [
                    "o_wslides_js_quiz_sequence_highlight",
                    "position-relative",
                    "my-3",
                ],
                applyChangeOnDrop: true,
            })
            .enable();
        this.host.registerCleanup(() => this.bindedSortable?.cleanup());
    }

    /**
     * @returns {Array}
     */
    _getQuestionsIds() {
        return Array.from(
            this.el.querySelectorAll(".o_wslides_js_lesson_quiz_question"),
        ).map((el) => el.dataset.questionId);
    }

    _modifyQuestionsSequence() {
        this.el
            .querySelectorAll(".o_wslides_js_lesson_quiz_question")
            .forEach((question, index) => {
                const seq = question.querySelector(
                    "span.o_wslides_quiz_question_sequence",
                );
                if (seq) {
                    seq.textContent = index + 1;
                }
            });
    }

    _reorderQuestions() {
        this.host.services.orm
            .webResequence("survey.question", this._getQuestionsIds())
            .then(this._modifyQuestionsSequence.bind(this));
    }

    _fetchQuiz() {
        return this.host
            .waitFor(rpc("/slides/slide/quiz/get", { slide_id: this.slide.id }))
            .then((quiz_data) => {
                this.slide.sessionAnswers = quiz_data.session_answers;
                this.quiz = {
                    description_safe: quiz_data.slide_description
                        ? markup(quiz_data.slide_description)
                        : "",
                    questions: quiz_data.slide_questions || [],
                    questionsCount: quiz_data.slide_questions.length,
                    quizAttemptsCount: quiz_data.quiz_attempts_count || 0,
                    quizKarmaGain: quiz_data.quiz_karma_gain || 0,
                    quizKarmaWon: quiz_data.quiz_karma_won || 0,
                    slideResources: quiz_data.slide_resource_ids || [],
                };
            });
    }

    _hideEditOptions() {
        for (const el of this.el.querySelectorAll(
            ".o_wslides_js_lesson_quiz_question .o_wslides_js_quiz_edit_del," +
                " .o_wslides_js_lesson_quiz_question .o_wslides_js_quiz_sequence_handler",
        )) {
            el.classList.add("d-none");
        }
    }

    _disableAnswers() {
        for (const el of this.el.querySelectorAll(
            ".o_wslides_js_lesson_quiz_question",
        )) {
            el.classList.add("completed-disabled");
        }
        for (const input of this.el.querySelectorAll("input[type=radio]")) {
            input.disabled = this.slide.completed;
        }
    }

    _renderAnswersHighlightingAndComments() {
        for (const question of this.el.querySelectorAll(
            ".o_wslides_js_lesson_quiz_question",
        )) {
            const questionId = question.dataset.questionId;
            const isCorrect = this.quiz.answers[questionId].is_correct;
            for (const answer of question.querySelectorAll("a.o_wslides_quiz_answer")) {
                for (const icon of answer.querySelectorAll("i")) {
                    icon.classList.add("d-none");
                }
                const radio = answer.querySelector("input[type=radio]");
                if (radio && radio.checked) {
                    if (isCorrect) {
                        answer.classList.remove("list-group-item-danger");
                        answer.classList.add("list-group-item-success");
                        const checkIcon = answer.querySelector("i.fa-check-circle");
                        if (checkIcon) {
                            checkIcon.classList.remove("d-none");
                        }
                    } else {
                        answer.classList.remove("list-group-item-success");
                        answer.classList.add("list-group-item-danger");
                        const timesIcon = answer.querySelector("i.fa-times-circle");
                        if (timesIcon) {
                            timesIcon.classList.remove("d-none");
                        }
                        const labelInput = answer.querySelector("label input");
                        if (labelInput) {
                            labelInput.checked = false;
                        }
                    }
                } else {
                    answer.classList.remove(
                        "list-group-item-danger",
                        "list-group-item-success",
                    );
                    const circleIcon = answer.querySelector("i.fa-circle");
                    if (circleIcon) {
                        circleIcon.classList.remove("d-none");
                    }
                }
            }
            const comment = this.quiz.answers[questionId].comment;
            if (comment) {
                const answerInfo = question.querySelector(
                    ".o_wslides_quiz_answer_info",
                );
                if (answerInfo) {
                    answerInfo.classList.remove("d-none");
                }
                const answerComment = question.querySelector(
                    ".o_wslides_quiz_answer_comment",
                );
                if (answerComment) {
                    answerComment.textContent = comment;
                }
            }
        }
    }

    _applySessionAnswers() {
        if (!this.slide.sessionAnswers || this.slide.sessionAnswers.length === 0) {
            return;
        }

        for (const question of this.el.querySelectorAll(
            ".o_wslides_js_lesson_quiz_question",
        )) {
            for (const answer of question.querySelectorAll("a.o_wslides_quiz_answer")) {
                const radio = answer.querySelector("input[type=radio]");
                if (
                    radio &&
                    !radio.checked &&
                    this.slide.sessionAnswers.includes(
                        parseInt(answer.dataset.answerId),
                    )
                ) {
                    radio.checked = true;
                }
            }
        }

        this.slide.sessionAnswers = false;
    }

    _renderValidationInfo() {
        const validationElem = this.el.querySelector(
            ".o_wslides_js_lesson_quiz_validation",
        );
        if (validationElem) {
            validationElem.replaceChildren(
                renderToElement("slide.slide.quiz.validation", { widget: this }),
            );
        }
    }

    /**
     * @param {Boolean} show
     */
    _toggleAdditionalResourceInfo(show) {
        const resourceInfo = document.getElementsByClassName(
            "o_wslides_js_lesson_quiz_resource_info",
        )[0];
        resourceInfo &&
            (show
                ? resourceInfo.classList.remove("d-none")
                : resourceInfo.classList.add("d-none"));
    }

    _renderJoinWidget() {
        const widgetLocation = this.el.querySelector(".o_wslides_join_course_widget");
        if (widgetLocation) {
            const joinBehavior = attachCourseJoin(this.host, widgetLocation, {
                isQuiz: true,
                channel: this.channel,
                isMember: this.isMember,
                isMemberOrInvited: this.isMemberOrInvited,
                publicUser: this.publicUser,
                beforeJoin: this._saveQuizAnswersToSession.bind(this),
                afterJoin: this._afterJoin.bind(this),
                joinMessage: _t("Join & Submit"),
            });

            if (
                !this.publicUser &&
                joinBehavior.channel.channelEnroll === "public" &&
                this.slide.sessionAnswers
            ) {
                joinBehavior.joinChannel(this.channel.channelId);
            }
        }
    }

    _getQuizAnswers() {
        return Array.from(this.el.querySelectorAll("input[type=radio]:checked")).map(
            (el) => parseInt(el.value),
        );
    }

    async _submitQuiz() {
        const data = await this.host.waitFor(
            rpc("/slides/slide/quiz/submit", {
                slide_id: this.slide.id,
                answer_ids: this._getQuizAnswers(),
            }),
        );
        if (data.error) {
            this._showErrorMessage(data.error);
            return;
        } else {
            this._hideErrorMessage();
        }
        Object.assign(this.quiz, data);
        const { rankProgress, completed, channel_completion: completion } = this.quiz;
        if ("description" in rankProgress) {
            rankProgress["description"] = markup(rankProgress["description"] || "");
            rankProgress["previous_rank"]["motivational"] = markup(
                rankProgress["previous_rank"]["motivational"] || "",
            );
            rankProgress["new_rank"]["motivational"] = markup(
                rankProgress["new_rank"]["motivational"] || "",
            );
        }
        if (completed) {
            this._disableAnswers();
            this.host.services.dialog.add(SlideQuizFinishDialog, {
                quiz: this.quiz,
                hasNext: this.slide.hasNext,
                onClickNext: (ev) => this._onClickNext(ev),
                userId: this.userId,
            });
            this.slide.completed = true;
            this.el.dispatchEvent(
                new CustomEvent("slide_completed", {
                    bubbles: true,
                    detail: {
                        slideId: this.slide.id,
                        channelCompletion: completion,
                        completed: true,
                    },
                }),
            );
        }
        this._hideEditOptions();
        this._renderAnswersHighlightingAndComments();
        this._renderValidationInfo();
        this._toggleAdditionalResourceInfo(!completed);
    }

    /**
     * @param {HTMLElement} questionEl
     * @returns {{id: *, sequence: number, text: *, answers: Array}}
     */
    _getQuestionDetails(questionEl) {
        const answers = [];
        for (const answerEl of questionEl.querySelectorAll(".o_wslides_quiz_answer")) {
            answers.push({
                id: answerEl.dataset.answerId,
                text_value: answerEl.dataset.text,
                is_correct: answerEl.dataset.isCorrect,
                comment: answerEl.dataset.comment,
            });
        }
        const seqEl = questionEl.querySelector(".o_wslides_quiz_question_sequence");
        return {
            id: questionEl.dataset.questionId,
            sequence: parseInt(seqEl ? seqEl.textContent : "0"),
            text: questionEl.dataset.title,
            answers: answers,
        };
    }

    _checkLocationHref() {
        if (
            window.location.href.includes("quiz_quick_create") &&
            this.quiz.questionsCount === 0
        ) {
            this._onCreateQuizClick();
        }
    }

    /**
     * @param {Event} ev
     * @param {HTMLElement} target
     */
    _onAnswerClick(ev, target) {
        ev.preventDefault();
        if (!this.slide.completed) {
            const radio = target.querySelector("input[type=radio]");
            if (radio) {
                radio.checked = true;
            }
        }
    }

    _onClickNext() {
        if (this.slide.hasNext) {
            this.el.dispatchEvent(
                new CustomEvent("slide_go_next", { bubbles: true, detail: {} }),
            );
        }
    }

    _onClickReset() {
        rpc("/slides/slide/quiz/reset", {
            slide_id: this.slide.id,
        }).then(function () {
            window.location.reload();
        });
    }

    _saveQuizAnswersToSession() {
        this._hideErrorMessage();

        return rpc("/slides/slide/quiz/save_to_session", {
            quiz_answers: {
                slide_id: this.slide.id,
                slide_answers: this._getQuizAnswers(),
            },
        });
    }

    _afterJoin() {
        this._saveQuizAnswersToSession().then(() => {
            window.location.reload();
        });
    }

    _onCreateQuizClick() {
        const newQuestionEl = this.el.querySelector(
            ".o_wslides_js_lesson_quiz_new_question",
        );
        const addBtn = this.el.querySelector(".o_wslides_js_quiz_add");
        if (addBtn) {
            addBtn.classList.add("d-none");
        }
        new QuestionFormBehavior(this.host, newQuestionEl, "beforeend", {
            slideId: this.slide.id,
            sequence: this.quiz.questionsCount + 1,
            ...this._questionFormCallbacks(),
        });
    }

    /**
     * @param {Event} ev
     * @param {HTMLElement} target
     */
    _onEditQuestionClick(ev, target) {
        const editedQuestion = target.closest(".o_wslides_js_lesson_quiz_question");
        const question = this._getQuestionDetails(editedQuestion);
        new QuestionFormBehavior(this.host, editedQuestion, "afterend", {
            editedQuestionEl: editedQuestion,
            question: question,
            slideId: this.slide.id,
            sequence: question.sequence,
            update: true,
            ...this._questionFormCallbacks(),
        });
        editedQuestion.style.display = "none";
    }

    _questionFormCallbacks() {
        return {
            onDisplayCreated: this._displayCreatedQuestion.bind(this),
            onDisplayUpdated: this._displayUpdatedQuestion.bind(this),
            onResetDisplay: this._resetDisplay.bind(this),
        };
    }

    /**
     * @param {Event} ev
     * @param {HTMLElement} target
     */
    _onDeleteQuestionClick(ev, target) {
        const question = target.closest(".o_wslides_js_lesson_quiz_question");
        const questionId = parseInt(question.dataset.questionId);
        this.host.services.dialog.add(ConfirmationDialog, {
            title: _t("Delete Question"),
            body: _t('Are you sure you want to delete this question "%(title)s"?', {
                title: markup`<strong>${question.dataset.title}</strong>`,
            }),
            cancel: () => {},
            cancelLabel: _t("No"),
            confirm: async () => {
                await this.host.services.orm.unlink("survey.question", [questionId]);
                this._deleteQuestion(questionId);
            },
            confirmLabel: _t("Yes"),
        });
    }

    /**
     * @param {QuestionFormBehavior} questionForm
     * @param {String} newQuestionRenderedTemplate
     */
    _displayCreatedQuestion(questionForm, newQuestionRenderedTemplate) {
        const questions = this.el.querySelectorAll(
            ".o_wslides_js_lesson_quiz_question",
        );
        const lastQuestion = questions[questions.length - 1];
        const questionEl = parseQuestionMarkup(newQuestionRenderedTemplate);
        if (lastQuestion) {
            lastQuestion.after(questionEl);
        } else {
            this.el.prepend(questionEl);
        }
        this.quiz.questionsCount++;
        questionForm.destroy();
        const addQuestionBtn = this.el.querySelector(".o_wslides_js_quiz_add_question");
        if (addQuestionBtn) {
            addQuestionBtn.classList.remove("d-none");
        }
    }

    /**
     * @param {QuestionFormBehavior} questionForm
     * @param {String} newQuestionRenderedTemplate
     * @param {HTMLElement} editedQuestionEl
     */
    _displayUpdatedQuestion(
        questionForm,
        newQuestionRenderedTemplate,
        editedQuestionEl,
    ) {
        editedQuestionEl.replaceWith(parseQuestionMarkup(newQuestionRenderedTemplate));
        questionForm.destroy();
    }

    /**
     * @param {QuestionFormBehavior} questionForm
     */
    _resetDisplay(questionForm) {
        if (questionForm.update) {
            questionForm.editedQuestionEl.style.display = "";
        } else {
            if (this.quiz.questionsCount > 0) {
                const addQuestionBtn = this.el.querySelector(
                    ".o_wslides_js_quiz_add_question",
                );
                if (addQuestionBtn) {
                    addQuestionBtn.classList.remove("d-none");
                }
            } else {
                const addQuizBtn = this.el.querySelector(".o_wslides_js_quiz_add_quiz");
                if (addQuizBtn) {
                    addQuizBtn.classList.remove("d-none");
                }
            }
        }
        questionForm.destroy();
    }

    /**
     * @param {Integer} questionId
     */
    _deleteQuestion(questionId) {
        const questionEl = this.el.querySelector(
            `.o_wslides_js_lesson_quiz_question[data-question-id="${questionId}"]`,
        );
        if (questionEl) {
            questionEl.remove();
        }
        this.quiz.questionsCount--;
        this._reorderQuestions();
        const newQuestionSeq = this.el.querySelector(
            ".o_wslides_js_lesson_quiz_new_question .o_wslides_quiz_question_sequence",
        );
        if (newQuestionSeq) {
            newQuestionSeq.textContent = parseInt(newQuestionSeq.textContent) - 1;
        }
        if (
            this.quiz.questionsCount === 0 &&
            !this.el.querySelector(".o_wsildes_quiz_question_input")
        ) {
            const addQuizBtn = this.el.querySelector(".o_wslides_js_quiz_add_quiz");
            if (addQuizBtn) {
                addQuizBtn.classList.remove("d-none");
            }
            const addQuestionBtn = this.el.querySelector(
                ".o_wslides_js_quiz_add_question",
            );
            if (addQuestionBtn) {
                addQuestionBtn.classList.add("d-none");
            }
            const validationEl = this.el.querySelector(
                ".o_wslides_js_lesson_quiz_validation",
            );
            if (validationEl) {
                validationEl.classList.add("d-none");
            }
        }
    }
}

export class QuizNoFullscreen extends CoursePage {
    static selector = ".o_wslides_lesson_main";

    dynamicContent = {
        ...this.dynamicContent,
        _root: {
            ...this.dynamicContent._root,
            "t-on-slide_go_next": this.onQuizNextSlide,
        },
    };

    start() {
        const quizEl = this.el.querySelector(".o_wslides_js_lesson_quiz");
        if (!quizEl) {
            this.quiz = null;
            return;
        }
        const slideData = quizEl.dataset;
        const channelData = this._extractChannelData(slideData);
        const parsedSlideData = {
            id: parseInt(slideData.id),
            name: slideData.name || "",
            hasNext: slideData.hasNext === "true" || slideData.hasNext === "1",
            completed: slideData.completed === "true" || slideData.completed === "1",
            isMember: slideData.isMember === "true" || slideData.isMember === "1",
            isMemberOrInvited:
                slideData.isMemberOrInvited === "true" ||
                slideData.isMemberOrInvited === "1",
            canSelfMarkCompleted:
                slideData.canSelfMarkCompleted === "true" ||
                slideData.canSelfMarkCompleted === "1",
            canSelfMarkUncompleted:
                slideData.canSelfMarkUncompleted === "true" ||
                slideData.canSelfMarkUncompleted === "1",
        };
        const quizData = {
            questions: this._extractQuestionsAndAnswers(),
            sessionAnswers: slideData.sessionAnswers
                ? JSON.parse(slideData.sessionAnswers)
                : [],
            quizKarmaMax: parseInt(slideData.quizKarmaMax) || 0,
            quizKarmaWon: parseInt(slideData.quizKarmaWon) || 0,
            quizKarmaGain: parseInt(slideData.quizKarmaGain) || 0,
            quizAttemptsCount: parseInt(slideData.quizAttemptsCount) || 0,
        };

        this.quiz = new QuizBehavior(
            this,
            { el: quizEl, slideData: parsedSlideData, channelData },
            quizData,
        );
        this.quiz.start();
    }

    onQuizNextSlide() {
        const quizEl = this.el.querySelector(".o_wslides_js_lesson_quiz");
        const url = quizEl?.dataset.nextSlideUrl;
        if (url) {
            window.location.replace(url);
        }
    }

    /**
     * @override
     */
    getSlide(slideId) {
        const slide = super.getSlide(...arguments);
        if (slide) {
            return slide;
        }
        const el = document.querySelector(
            `.o_wslides_js_lesson_quiz[data-id="${slideId}"]`,
        );
        return el ? el.dataset : undefined;
    }

    /**
     * @override
     */
    toggleCompletionButton(slideData, completed = true) {
        super.toggleCompletionButton(...arguments);

        if (
            this.quiz &&
            this.quiz.slide.id === slideData.id &&
            !completed &&
            this.quiz.quiz.questionsCount
        ) {
            this.quiz.quiz.answers = null;
            this.quiz.slide.sessionAnswers = null;
            this.quiz.slide.completed = false;
            this.quiz._fetchQuiz().then(() => {
                this.quiz.rerender();
                this.quiz._renderValidationInfo();
            });
        }

        const doneButton = document.querySelector(".o_wslides_done_button");
        if (doneButton && completed) {
            doneButton.classList.remove(
                "o_wslides_done_button",
                "disabled",
                "btn-primary",
                "text-white",
            );
            doneButton.classList.add("o_wslides_undone_button", "btn-light");
            doneButton.textContent = _t("Mark To Do");
            doneButton.removeAttribute("title");
            doneButton.removeAttribute("aria-disabled");
            doneButton.setAttribute(
                "href",
                `/slides/slide/${encodeURIComponent(slideData.id)}/set_uncompleted`,
            );
        }
    }

    _extractChannelData(slideData) {
        return {
            channelId: parseInt(slideData.channelId) || slideData.channelId,
            channelEnroll: slideData.channelEnroll,
            channelRequestedAccess: slideData.channelRequestedAccess || false,
            signupAllowed:
                slideData.signupAllowed === "true" || slideData.signupAllowed === "1",
        };
    }

    /**
     * @return {Array<Object>}
     */
    _extractQuestionsAndAnswers() {
        const questions = [];
        for (const question of this.el.querySelectorAll(
            ".o_wslides_js_lesson_quiz_question",
        )) {
            const answers = [];
            for (const answer of question.querySelectorAll(".o_wslides_quiz_answer")) {
                answers.push({
                    id: parseInt(answer.dataset.answerId),
                    text: answer.dataset.text,
                });
            }
            questions.push({
                id: parseInt(question.dataset.questionId),
                title: question.dataset.title,
                answer_ids: answers,
            });
        }
        return questions;
    }
}

registry
    .category("public.interactions")
    .add("website_slides.quiz_no_fullscreen", QuizNoFullscreen);
