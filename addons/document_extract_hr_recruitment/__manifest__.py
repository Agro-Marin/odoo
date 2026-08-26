{
    "name": "Applicant CV Extraction",
    "version": "19.0.1.0.0",
    "category": "Human Resources/Recruitment",
    "summary": "Read an applicant's CV with document_extract",
    "description": """
Applicant CV Extraction
=======================

Puts ``mixin.document.extract`` on ``hr.applicant``, replacing
``hr_recruitment_extract``'s reading of a CV.

A CV is the document type this framework is best at and the old stack was worst
at. It is text: a local text reader gets the whole of it for nothing, and a
generative strategy reads a name, an address and a phone number out of that text
without a page ever reaching a service that charges by the page. The module it
replaces sent every CV to a remote reader, including the ones that were already
plain text.

Nothing is overwritten
----------------------
A name, an email and a phone number, and each written only into emptiness.
``hr_recruitment_extract`` preferred the reading -- ``self.partner_name =
name_ocr or self.partner_name`` -- so a recruiter who had corrected a misread
name watched the next reading put it back. A person who typed something into a
field has said something the document did not.

Only a new applicant
--------------------
Reading is offered while the applicant sits in the first stage of their job's
pipeline, which is what the replaced module meant by an extractable state. After
that, somebody has been through the record, and a reading that rewrites it is
correcting a person from a document they have already read.
    """,
    "author": "AgroMarin",
    "website": "https://agromarin.com",
    "license": "LGPL-3",
    "depends": [
        "hr_recruitment",
        "document_extract",
    ],
    "data": [
        "views/hr_applicant_views.xml",
    ],
}
