"""Declarative SQL table objects for ORM models.

Descriptor classes (Constraint, Index, UniqueIndex) used as class attributes
on model definitions to declare SQL constraints and indexes::

    class MyModel(models.Model):
        _name = "my.model"

        _code_uniq = models.Constraint("unique(code)", "Code must be unique!")
        _name_idx = models.Index("(name)")
        _active_uniq = models.UniqueIndex(
            "(name) WHERE active IS TRUE", "Active name must be unique!"
        )
"""

import typing

from odoo.tools import sql

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from psycopg.errors import Diagnostic

    from ..runtime import Environment, Registry

    BaseModel = typing.Any  # forward reference

    ConstraintMessageType = str | Callable[[Environment, Diagnostic | None], str]
    IndexDefinitionType = str | Callable[[Registry], str]


class TableObject:
    """Declares a SQL object related to the model.

    The identifier of the SQL object will be "{model._table}_{name}".
    """

    name: str
    message: ConstraintMessageType = ""
    _module: str = ""

    def __init__(self) -> None:
        # name is unique within the model; full_name is the database identifier
        self.name = ""

    def __set_name__(self, owner: type, name: str) -> None:
        # SQL objects must be private members: not meant to be accessed from a
        # model, and kept out of the way when listing fields.
        if not name.startswith("_"):
            raise TypeError(
                f"Name {name!r} of SQL object on {owner.__name__!r} must start with '_'"
            )
        if name.startswith(f"_{owner.__name__}__"):
            raise TypeError(
                f"Name {name!r} of SQL object on {owner.__name__!r} must not be mangled "
                "(use a single leading underscore, not two)"
            )
        self.name = name[1:]
        if getattr(owner, "pool", None) is None:  # models.is_model_definition(owner)
            # only for fields on definition classes, not registry classes
            self._module = owner._module
            owner._table_object_definitions.append(self)

    def get_definition(self, registry: Registry) -> str:
        raise NotImplementedError

    def full_name(self, model: BaseModel) -> str:
        assert self.name, "The table object is not named"
        name = f"{model._table}_{self.name}"
        return sql.make_identifier(name)

    def get_error_message(
        self, model: BaseModel, diagnostics: Diagnostic | None = None
    ) -> str:
        """Build an error message for the object/constraint.

        :param model: Optional model on which the constraint is defined
        :param diagnostics: Optional diagnostics from the raised exception
        :return: Translated error for the user
        """
        message = self.message
        if callable(message):
            return message(model.env, diagnostics)
        return message

    def apply_to_database(self, model: BaseModel) -> None:
        raise NotImplementedError

    def __str__(self) -> str:
        return f"({self.name!r}, {self.message!r})"


class Constraint(TableObject):
    """SQL table constraint.

    The definition of the constraint is used to `ADD CONSTRAINT` on the table.
    """

    def __init__(
        self,
        definition: str,
        message: ConstraintMessageType = "",
    ) -> None:
        """Declare an SQL table constraint.

        ``definition`` is the SQL added to the table; ``message`` is shown on
        violation (empty for a default message). Example definitions::

            CHECK (x > 0)
            FOREIGN KEY (abc) REFERENCES some_table(id)
            UNIQUE (user_id)
        """
        super().__init__()
        self._definition = definition
        if message:
            self.message = message

    def get_definition(self, registry: Registry) -> str:
        return self._definition

    def apply_to_database(self, model: BaseModel) -> None:
        cr = model.env.cr
        conname = self.full_name(model)
        definition = self.get_definition(model.pool)
        current_definition = sql.constraint_definition(cr, model._table, conname)
        if current_definition == definition:
            return

        if current_definition:
            # constraint exists but its definition may have changed
            sql.drop_constraint(cr, model._table, conname)

        model.pool.post_constraint(
            cr,
            lambda cr: sql.add_constraint(cr, model._table, conname, definition),
            conname,
        )


class Index(TableObject):
    """Index on the table.

    ``CREATE INDEX ... ON model_table <your definition>``.
    """

    unique: bool = False

    def __init__(self, definition: IndexDefinitionType):
        """SQL index. ``definition`` is the SQL used to create it. Examples::

            (group_id, active) WHERE active IS TRUE
            USING btree (group_id, user_id)
        """
        super().__init__()
        self._index_definition = definition

    def _definition_clause(self, registry: Registry) -> str:
        """Evaluate the (possibly callable) index definition to its SQL clause."""
        if callable(self._index_definition):
            return self._index_definition(registry)
        return self._index_definition

    def _format_definition(self, clause: str) -> str:
        if not clause:
            return ""
        return f"{'UNIQUE ' if self.unique else ''}INDEX {clause}"

    def get_definition(self, registry: Registry) -> str:
        return self._format_definition(self._definition_clause(registry))

    def apply_to_database(self, model: BaseModel) -> None:
        cr = model.env.cr
        conname = self.full_name(model)
        # Evaluate the definition once: a callable definition must not be invoked
        # twice (the comment and the index clause would diverge if it is impure).
        definition_clause = self._definition_clause(model.pool)
        definition = self._format_definition(definition_clause)
        db_definition, db_comment = sql.index_definition(cr, conname)
        if db_comment == definition or (not db_comment and db_definition):
            # keep when the definition matches the comment in the database, or when
            # an index has no comment (used by support to tweak indexes manually)
            return

        if db_definition:
            # index exists but its definition may have changed
            sql.drop_index(cr, conname, model._table)

        if not definition_clause:
            # Don't create index with an empty definition
            return
        model.pool.post_constraint(
            cr,
            lambda cr: sql.add_index(
                cr,
                conname,
                model._table,
                comment=definition,
                definition=definition_clause,
                unique=self.unique,
            ),
            conname,
        )


class UniqueIndex(Index):
    """Unique index on the table.

    ``CREATE UNIQUE INDEX ... ON model_table <your definition>``.
    """

    unique = True

    def __init__(
        self,
        definition: IndexDefinitionType,
        message: ConstraintMessageType = "",
    ):
        """Unique SQL index. ``definition`` is the SQL used to create it;
        ``message`` is shown on violation. Examples::

            (group_id, active) WHERE active IS TRUE
            USING btree (group_id, user_id)
        """
        super().__init__(definition)
        if message:
            self.message = message
