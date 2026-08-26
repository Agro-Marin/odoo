{
    "name": "Expense Receipt Extraction",
    "version": "19.0.1.0.0",
    "category": "Human Resources/Expenses",
    "summary": "Read an expense's receipt with document_extract",
    "description": """
Expense Receipt Extraction
==========================

Puts ``mixin.document.extract`` on ``hr.expense``, replacing
``hr_expense_extract``'s reading of a receipt. Both declare ``extract_state``,
so a model cannot carry the two and that module is marked uninstallable in the
same change -- the third pair after the vendor bill and the CV.

What a receipt says, and what it does not
----------------------------------------
A merchant, a date, a total and the currency it is written in. The ``receipt``
schema already carried all four, so nothing here extends it.

Two of those fields have a default rather than an empty value, so the mixin's
rule -- write only into emptiness -- cannot be read off the field alone. A date
defaults to today and a description to "Untitled Expense". The reading is
therefore applied to a date the employee has not moved off the day the record
was made, and to a description they have not renamed. Both tests are the ones
the replaced module used; what changed is that a value a person did type is now
left alone in every case rather than only some.

A total is not a price
----------------------
An amount read off a receipt is written to the expense's own amount, in the
currency the receipt names, and converted to the company's for the accounting
figure. Where the expense carries a product with a catalogue price -- a per-diem,
a mileage rate -- the printed total is not what the company owes, and that case
belongs to ``document_extract_hr_expense_predict`` along with the product.
    """,
    "author": "AgroMarin",
    "website": "https://agromarin.com",
    "license": "LGPL-3",
    "depends": [
        "hr_expense",
        "document_extract",
    ],
    "data": [
        "views/hr_expense_views.xml",
    ],
}
