{
    "name": "Applicant CV Skill Extraction",
    "version": "19.0.1.0.0",
    "category": "Human Resources/Recruitment",
    "summary": "Record the skills a CV names against the skill catalogue",
    "description": """
Applicant CV Skill Extraction
=============================

Matches the skills read off a CV to ``hr.skill`` records and attaches them to
the applicant. Separate from the reading itself because the skill catalogue is
``hr_recruitment_skills``' and not every deployment carries it.

Read, not scanned
-----------------
``hr_recruitment_extract`` did not read skills. It lowercased the whole OCR text
and searched it for the name of every skill in the catalogue, which finds a
skill in any sentence that happens to contain the word -- "no experience with
Java", a former employer called Ruby, an address on Angular Street. The schema
asks for the skills instead, and what comes back is what the document presented
as skills.

Matched, never invented
-----------------------
A read skill has to match a catalogue entry by name, case-insensitively and
exactly. A CV naming something the catalogue does not carry is not evidence that
it should: a skill invented from a misread word is a catalogue entry nobody
curated, and every later applicant can then be matched against it.

A skill already on the applicant is left alone, including its level. The level a
recruiter set is a judgment about a person, and a document that mentions the
skill again is not new information about it.
    """,
    "author": "AgroMarin",
    "website": "https://agromarin.com",
    "license": "LGPL-3",
    "depends": [
        "document_extract_hr_recruitment",
        "hr_recruitment_skills",
    ],
    "auto_install": True,
}
