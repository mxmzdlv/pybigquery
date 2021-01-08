from sqlalchemy.dialects.postgresql import array
from sqlalchemy.sql import expression, operators, sqltypes

__all__ = ["array", "struct"]


class STRUCT(sqltypes.Indexable, sqltypes.TypeEngine):
    # NOTE: STRUCT names/types aren't currently supported.

    __visit_name__ = "STRUCT"

    class Comparator(sqltypes.Indexable.Comparator):
        def _setup_getitem(self, index):
            return operators.getitem, index, self.type

    comparator_factory = Comparator


class struct(expression.ClauseList, expression.ColumnElement):
    """ Create a BigQuery struct literal from a collection of named expressions/clauses.
    """
    # NOTE: Struct subfields aren't currently propagated/validated.

    __visit_name__ = "struct"

    def __init__(self, clauses, field=None, **kw):
        self.field = field
        self.type = STRUCT()
        super().__init__(*clauses, **kw)

    def _bind_param(self, operator, obj, _assume_scalar=False, type_=None):
        if operator is operators.getitem:
            # TODO:
            # - Validate field in clauses (or error if no clauses)
            # - If the field is a sub-struct, return with all clauses, otherwise none.
            return struct([], field=obj)

    def self_group(self, against=None):
        if not self.field and against in (operators.getitem,):
            return expression.Grouping(self)
        else:
            return self
