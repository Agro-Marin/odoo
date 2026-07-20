# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Migrate slide.question / slide.answer → survey.question / survey.question.answer.

Quiz slides now use survey.survey to store their questions, unifying the data
model with certifications. This pre-migration creates survey records for each
quiz slide that has slide_question rows, copies questions and answers into
survey models, remaps XML IDs, and cleans up.

Uses temporary columns (_marin_from_*) for guaranteed correct ID mapping
instead of fragile ROW_NUMBER approaches.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    # Check if old tables exist (they won't on fresh installs)
    cr.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_name = 'slide_question'
        )
    """)
    if not cr.fetchone()[0]:
        _logger.info("No slide_question table found — skipping quiz migration")
        return

    cr.execute("SELECT COUNT(*) FROM slide_question")
    question_count = cr.fetchone()[0]
    if not question_count:
        _logger.info("No slide_question rows — skipping quiz migration")
        return

    _logger.info(
        "Migrating %d slide.question records to survey.question", question_count
    )

    # Step 1: Add temp columns for safe ID mapping
    cr.execute(
        "ALTER TABLE survey_survey ADD COLUMN IF NOT EXISTS _marin_from_slide_id INTEGER"
    )
    cr.execute(
        "ALTER TABLE survey_question ADD COLUMN IF NOT EXISTS _marin_from_slide_question_id INTEGER"
    )
    cr.execute(
        "ALTER TABLE survey_question_answer ADD COLUMN IF NOT EXISTS _marin_from_slide_answer_id INTEGER"
    )

    # Step 2: Create survey.survey records for quiz slides that have questions but no survey
    cr.execute("""
        INSERT INTO survey_survey (
            title, survey_type, access_token, scoring_type, scoring_success_min,
            questions_layout, questions_selection, access_mode,
            certification, active, _marin_from_slide_id,
            create_uid, create_date, write_uid, write_date
        )
        SELECT DISTINCT ON (ss.id)
            ss.name,
            'custom',
            gen_random_uuid()::text,
            'scoring_without_answers',
            100.0,
            'one_page',
            'all',
            'public',
            false,
            true,
            ss.id,
            ss.create_uid, NOW(), ss.write_uid, NOW()
        FROM slide_slide ss
        JOIN slide_question sq ON sq.slide_id = ss.id
        WHERE ss.survey_id IS NULL
    """)
    surveys_created = cr.rowcount
    _logger.info("Created %d survey.survey records for quiz slides", surveys_created)

    # Link surveys to slides
    cr.execute("""
        UPDATE slide_slide ss
        SET survey_id = sv.id
        FROM survey_survey sv
        WHERE sv._marin_from_slide_id = ss.id
          AND ss.survey_id IS NULL
    """)

    # Step 3: Copy slide_question → survey_question
    # Only migrate questions for slides whose survey was just created (step 2),
    # not certification slides that already had their own survey with questions.
    cr.execute("""
        INSERT INTO survey_question (
            survey_id, title, sequence, question_type, is_page,
            _marin_from_slide_question_id,
            create_uid, create_date, write_uid, write_date
        )
        SELECT
            ss.survey_id, sq.question, sq.sequence, 'simple_choice', false,
            sq.id,
            sq.create_uid, sq.create_date, sq.write_uid, sq.write_date
        FROM slide_question sq
        JOIN slide_slide ss ON sq.slide_id = ss.id
        JOIN survey_survey sv ON ss.survey_id = sv.id
        WHERE sv._marin_from_slide_id IS NOT NULL
    """)
    questions_migrated = cr.rowcount
    _logger.info("Migrated %d slide_question → survey_question", questions_migrated)

    # Step 4: Copy slide_answer → survey_question_answer
    cr.execute("""
        INSERT INTO survey_question_answer (
            question_id, value, sequence, is_correct, answer_score, comment,
            _marin_from_slide_answer_id,
            create_uid, create_date, write_uid, write_date
        )
        SELECT
            sq_new.id, sa.text_value, sa.sequence, sa.is_correct,
            CASE WHEN sa.is_correct THEN 1.0 ELSE 0.0 END,
            sa.comment,
            sa.id,
            sa.create_uid, sa.create_date, sa.write_uid, sa.write_date
        FROM slide_answer sa
        JOIN slide_question sq_old ON sa.question_id = sq_old.id
        JOIN survey_question sq_new ON sq_new._marin_from_slide_question_id = sq_old.id
    """)
    answers_migrated = cr.rowcount
    _logger.info("Migrated %d slide_answer → survey_question_answer", answers_migrated)

    # Step 5: Remap XML IDs for demo/data records
    cr.execute("""
        UPDATE ir_model_data imd
        SET model = 'survey.question', res_id = sq.id
        FROM survey_question sq
        WHERE imd.model = 'slide.question'
          AND sq._marin_from_slide_question_id = imd.res_id
    """)
    cr.execute("""
        UPDATE ir_model_data imd
        SET model = 'survey.question.answer', res_id = sqa.id
        FROM survey_question_answer sqa
        WHERE imd.model = 'slide.answer'
          AND sqa._marin_from_slide_answer_id = imd.res_id
    """)

    # Clean up remaining XML IDs that weren't remapped
    cr.execute(
        "DELETE FROM ir_model_data WHERE model IN ('slide.question', 'slide.answer')"
    )

    # Step 6: Clean up ir_model and ir_model_fields
    cr.execute("DELETE FROM ir_model WHERE model IN ('slide.question', 'slide.answer')")
    cr.execute(
        "DELETE FROM ir_model_fields WHERE model IN ('slide.question', 'slide.answer')"
    )
    cr.execute(
        "UPDATE ir_model_fields SET relation = 'survey.question' WHERE relation = 'slide.question'"
    )
    cr.execute(
        "UPDATE ir_model_fields SET relation = 'survey.question.answer' WHERE relation = 'slide.answer'"
    )

    # Step 7: Drop temp columns and advance sequences
    cr.execute("ALTER TABLE survey_survey DROP COLUMN IF EXISTS _marin_from_slide_id")
    cr.execute(
        "ALTER TABLE survey_question DROP COLUMN IF EXISTS _marin_from_slide_question_id"
    )
    cr.execute(
        "ALTER TABLE survey_question_answer DROP COLUMN IF EXISTS _marin_from_slide_answer_id"
    )

    cr.execute(
        "SELECT setval('survey_survey_id_seq', COALESCE(MAX(id), 1), true) FROM survey_survey"
    )
    cr.execute(
        "SELECT setval('survey_question_id_seq', COALESCE(MAX(id), 1), true) FROM survey_question"
    )
    cr.execute(
        "SELECT setval('survey_question_answer_id_seq', COALESCE(MAX(id), 1), true) FROM survey_question_answer"
    )

    _logger.info(
        "Quiz migration complete: %d surveys, %d questions, %d answers",
        surveys_created,
        questions_migrated,
        answers_migrated,
    )
