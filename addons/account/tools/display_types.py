#: Display types that carry no accounting: they exist for layout only, so they
#: hold no account and no amount. It lives here rather than on the model because
#: both ``account.move`` and ``account.move.line`` need it, and each already
#: imports the other -- a constant on either one closes that loop into a cycle.
NON_ACCOUNTABLE_DISPLAY_TYPES = ("line_section", "line_subsection", "line_note")
