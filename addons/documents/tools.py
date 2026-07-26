"""Helpers shared across the documents module.

The parsed form of ``user_folder_id``, and mimetype classification.
"""


class UserFolder:
    """A parsed ``documents.document.user_folder_id``.

    ``user_folder_id`` is a *virtual* parent: either one of the drive roots
    below, or a real ``documents.document`` folder id. It travels as a string
    because that is what the web client sends and what the search panel keys its
    tree on -- ``"MY"``, ``"COMPANY"``, ``"12"``.

    Left as a bare string, every consumer re-derived its meaning with
    ``value.isnumeric()`` and a chain of equality tests, spread over the model,
    its search method, the wizards and the controllers. That is where several
    bugs lived: an ``int`` reaching ``isnumeric`` as an ``AttributeError``, a
    ``False`` reaching it the same way, and the search panel's counters keying a
    tree on values that were sometimes ``str`` and sometimes ``int``. Parsing
    once, here, makes those unrepresentable.

    The wire format is unchanged: ``str(user_folder)`` round-trips.
    """

    MY = "MY"
    COMPANY = "COMPANY"
    SHARED = "SHARED"
    RECENT = "RECENT"
    TRASH = "TRASH"
    FOLDER = "FOLDER"  # not a wire value: the kind of a real folder id

    #: Roots a document can actually be filed in; the others are views over
    #: documents filed elsewhere ("Shared with me", "Recent") or a state
    #: ("Trash"), so creating or moving into them is meaningless.
    WRITABLE_ROOTS = frozenset({MY, COMPANY})
    VIRTUAL_ROOTS = frozenset({MY, COMPANY, SHARED, RECENT, TRASH})

    __slots__ = ("folder_id", "kind")

    def __init__(self, kind: str, folder_id: int | None = None) -> None:
        """Build a parsed value; prefer :meth:`parse` for untrusted input."""
        self.kind = kind
        self.folder_id = folder_id

    @classmethod
    def parse(cls, value: object) -> UserFolder | None:
        """Return the parsed value, or ``None`` when nothing was specified.

        :raises ValueError: on a value that is neither a virtual root nor a
            folder id. Callers facing the ORM or a route translate that into
            their own ``UserError`` / ``BadRequest``.
        """
        if value is None or value is False or value == "":
            return None
        # `bool` first: it is an `int` subclass, and `True` would parse as
        # folder 1.
        if isinstance(value, bool):
            raise ValueError(f"Unexpected user_folder_id value {value!r}")
        if isinstance(value, int):
            return cls(cls.FOLDER, value)
        if not isinstance(value, str):
            raise ValueError(f"Unexpected user_folder_id value {value!r}")
        if value in cls.VIRTUAL_ROOTS:
            return cls(value)
        if value.isnumeric():
            return cls(cls.FOLDER, int(value))
        raise ValueError(f"Unknown searched value {value}")

    @property
    def is_folder(self) -> bool:
        """Whether this designates a real folder rather than a virtual root."""
        return self.kind == self.FOLDER

    @property
    def is_writable_root(self) -> bool:
        """Whether documents may be created or moved directly into it."""
        return self.kind in self.WRITABLE_ROOTS

    def __str__(self) -> str:
        """Render back to the wire format the client sends and expects."""
        return str(self.folder_id) if self.is_folder else self.kind

    def __repr__(self) -> str:
        """Show the wire value, which is what call sites reason about."""
        return f"UserFolder({self!s})"

    def __eq__(self, other: object) -> bool:
        """Compare by kind and folder id, so equal values are interchangeable."""
        if isinstance(other, UserFolder):
            return (self.kind, self.folder_id) == (other.kind, other.folder_id)
        return NotImplemented

    def __hash__(self) -> int:
        """Hash with `__eq__` so parsed values work as dict keys."""
        return hash((self.kind, self.folder_id))


def is_mimetype_textual(mimetype: str) -> bool:
    """Return whether the given mimetype represents textual content.

    A falsy or malformed mimetype (no ``/``) is simply not textual, rather than
    an AttributeError/ValueError that would surface as a 500 in the public
    thumbnail route.
    """
    maintype, _, subtype = (mimetype or "").partition("/")
    return maintype == "text" or (
        maintype == "application" and subtype in {"documents-email", "json", "xml"}
    )
