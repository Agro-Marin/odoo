from odoo.tools.translate import LazyTranslate

_lt = LazyTranslate(__name__)

SURVEY_SAMPLE = {
    "survey_type": "survey",
    "title": _lt("Feedback Form"),
    "description": _lt(
        "Please complete this very short survey to let us know how satisfied your "
        "are with our products.<br>Your responses will help us improve our product "
        "range to serve you even better."
    ),
    "description_done": _lt(
        "Thank you very much for your feedback. We highly value your opinion!"
    ),
    "progression_mode": "number",
    "questions_layout": "page_per_question",
    "question_and_page_ids": [
        (
            0,
            0,
            {
                "title": _lt("How frequently do you use our products?"),
                "question_type": "simple_choice",
                "constr_mandatory": True,
                "suggested_answer_ids": [
                    (
                        0,
                        0,
                        {"value": _lt("Often (1-3 times per week)")},
                    ),
                    (
                        0,
                        0,
                        {"value": _lt("Rarely (1-3 times per month)")},
                    ),
                    (
                        0,
                        0,
                        {"value": _lt("Never (less than once a month)")},
                    ),
                ],
            },
        ),
        (
            0,
            0,
            {
                "title": _lt("How many orders did you pass during the last 6 months?"),
                "question_type": "numerical_box",
            },
        ),
        (
            0,
            0,
            {
                "title": _lt(
                    "How likely are you to recommend the following products to a friend?"
                ),
                "question_type": "matrix",
                "matrix_subtype": "simple",
                "suggested_answer_ids": [
                    (
                        0,
                        0,
                        {"value": _lt("Unlikely")},
                    ),
                    (
                        0,
                        0,
                        {"value": _lt("Neutral")},
                    ),
                    (
                        0,
                        0,
                        {"value": _lt("Likely")},
                    ),
                ],
                "matrix_row_ids": [
                    (
                        0,
                        0,
                        {"value": _lt("Red Pen")},
                    ),
                    (
                        0,
                        0,
                        {"value": _lt("Blue Pen")},
                    ),
                    (
                        0,
                        0,
                        {"value": _lt("Yellow Pen")},
                    ),
                ],
            },
        ),
    ],
}

ASSESSMENT_SAMPLE = {
    "survey_type": "assessment",
    "title": _lt("Certification"),
    "certification": True,
    "access_mode": "token",
    "is_time_limited": True,
    "time_limit": 15,
    "is_attempts_limited": True,
    "attempts_limit": 1,
    "progression_mode": "number",
    "scoring_type": "scoring_without_answers",
    "users_can_go_back": True,
    "description": _lt(
        "Welcome to this Odoo certification. You will receive 2 random questions "
        'out of a pool of 3.(<span style="font-style: italic">Cheating on your '
        "neighbors will not help!</span> \U0001f601).<br>Good luck!"
    ),
    "description_done": _lt("Thank you. We will contact you soon."),
    "questions_layout": "page_per_section",
    "questions_selection": "random",
    "question_and_page_ids": [
        (
            0,
            0,
            {
                "title": _lt("Odoo Certification"),
                "is_page": True,
                "question_type": False,
                "random_questions_count": 2,
            },
        ),
        (
            0,
            0,
            {
                "title": _lt('What does "ODOO" stand for?'),
                "question_type": "simple_choice",
                "suggested_answer_ids": [
                    (
                        0,
                        0,
                        {"value": _lt('It\'s a Belgian word for "Management"')},
                    ),
                    (
                        0,
                        0,
                        {"value": _lt("Object-Directed Open Organization")},
                    ),
                    (
                        0,
                        0,
                        {
                            "value": _lt(
                                "Organizational Development for Operation Officers"
                            )
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "value": _lt("It does not mean anything specific"),
                            "is_correct": True,
                            "answer_score": 10,
                        },
                    ),
                ],
            },
        ),
        (
            0,
            0,
            {
                "title": _lt(
                    'On Survey questions, one can define "placeholders". But what are they for?'
                ),
                "question_type": "simple_choice",
                "suggested_answer_ids": [
                    (
                        0,
                        0,
                        {
                            "value": _lt(
                                "They are a default answer, used if the participant skips the question"
                            )
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "value": _lt(
                                "It is a small bit of text, displayed to help participants answer"
                            ),
                            "is_correct": True,
                            "answer_score": 10,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "value": _lt(
                                "They are technical parameters that guarantees the responsiveness of the page"
                            )
                        },
                    ),
                ],
            },
        ),
        (
            0,
            0,
            {
                "title": _lt("What does one need to get to pass an Odoo Survey?"),
                "question_type": "simple_choice",
                "suggested_answer_ids": [
                    (
                        0,
                        0,
                        {
                            "value": _lt(
                                "It is an option that can be different for each Survey"
                            ),
                            "is_correct": True,
                            "answer_score": 10,
                        },
                    ),
                    (
                        0,
                        0,
                        {"value": _lt("One needs to get 50% of the total score")},
                    ),
                    (
                        0,
                        0,
                        {
                            "value": _lt(
                                "One needs to answer at least half the questions correctly"
                            )
                        },
                    ),
                ],
            },
        ),
    ],
}
LIVE_SESSION_SAMPLE = {
    "survey_type": "live_session",
    "title": _lt("Live Session"),
    "description": _lt(
        "How good of a presenter are you? Let's find out!<br>"
        "But first, keep listening to the host."
    ),
    "description_done": _lt("Thank you for your participation, hope you had a blast!"),
    "progression_mode": "number",
    "scoring_type": "scoring_with_answers",
    "questions_layout": "page_per_question",
    "session_speed_rating": True,
    "session_speed_rating_time_limit": 90,
    "question_and_page_ids": [
        (
            0,
            0,
            {
                "title": _lt(
                    "What is the best way to catch the attention of an audience?"
                ),
                "question_type": "simple_choice",
                "suggested_answer_ids": [
                    (
                        0,
                        0,
                        {
                            "value": _lt(
                                "Speak softly so that they need to focus to hear you"
                            )
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "value": _lt(
                                "Use a fun visual support, like a live presentation"
                            ),
                            "is_correct": True,
                            "answer_score": 20,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "value": _lt(
                                "Show them slides with a ton of text they need to read fast"
                            )
                        },
                    ),
                ],
            },
        ),
        (
            0,
            0,
            {
                "title": _lt("What is a frequent mistake public speakers do?"),
                "question_type": "simple_choice",
                "suggested_answer_ids": [
                    (
                        0,
                        0,
                        {"value": _lt("Practice in front of a mirror")},
                    ),
                    (
                        0,
                        0,
                        {
                            "value": _lt("Speak too fast"),
                            "is_correct": True,
                            "answer_score": 20,
                        },
                    ),
                    (
                        0,
                        0,
                        {"value": _lt("Use humor and make jokes")},
                    ),
                ],
            },
        ),
        (
            0,
            0,
            {
                "title": _lt(
                    "Why should you consider making your presentation more fun with a small quiz?"
                ),
                "question_type": "multiple_choice",
                "suggested_answer_ids": [
                    (
                        0,
                        0,
                        {
                            "value": _lt(
                                "It helps attendees focus on what you are saying"
                            ),
                            "is_correct": True,
                            "answer_score": 20,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "value": _lt("It is more engaging for your audience"),
                            "is_correct": True,
                            "answer_score": 20,
                        },
                    ),
                    (
                        0,
                        0,
                        {
                            "value": _lt(
                                "It helps attendees remember the content of your presentation"
                            ),
                            "is_correct": True,
                            "answer_score": 20,
                        },
                    ),
                ],
            },
        ),
    ],
}
