{
    "name": "Recurrence Mixins",
    "version": "19.0.1.0.0",
    "category": "Hidden",
    "summary": "Reusable recurrence rule mixin: repeat every N units, forever or until a date.",
    "description": """
The "every N units, until ..." half of a recurrence, in one place.

``project.task.recurrence`` and ``planning.recurrency`` had each grown the same
rule independently: the same four unit values, the same two policy values, the
same positive-interval rule written twice -- once as a Python constraint and
once as a SQL CHECK -- and the same step-to-the-next-occurrence helper under two
names. This module owns that vocabulary so a further consumer cannot invent a
fifth spelling of "week".

Ships a mixin only -- no concrete model, no data, no views. Deliberately does
not own ``repeat_until`` (a Date for one consumer and a Datetime for the other,
which is a real difference) nor the occurrence generator (task copying and
resource-availability walking are not variations on a theme).
    """,
    "author": "AgroMarin",
    "website": "https://www.agromarin.mx",
    "license": "LGPL-3",
    "depends": ["base"],
}
