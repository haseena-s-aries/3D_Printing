"""mssql-django with one adaptation: filtered unique indexes cannot contain NOT.

Django renders UniqueConstraint(condition=~Q(field="")) as `NOT ([field] = N'')`, which SQL Server rejects in a filtered
index. That exact form is rewritten to the equivalent `[field] <> N''` (the columns are NOT NULL); any other negated
condition is refused with a clear error instead of being guessed.
"""
import re

from mssql.base import DatabaseWrapper as MssqlDatabaseWrapper
from mssql.schema import DatabaseSchemaEditor as MssqlSchemaEditor

NEGATED_EQUALITY = re.compile(r"^NOT \((\[\w+\]) = (N?'(?:[^']|'')*')\)$")
NEGATION = re.compile(r"(?<![A-Za-z])NOT\s*\(", re.IGNORECASE)  # `IS NOT NULL` is fine in a filtered index


def filtered_condition(condition):
    if not condition or not NEGATION.search(condition):
        return condition
    m = NEGATED_EQUALITY.match(condition.strip())
    if not m:
        raise ValueError(f"SQL Server filtered indexes cannot express this condition: {condition}")
    return f"{m.group(1)} <> {m.group(2)}"


class DatabaseSchemaEditor(MssqlSchemaEditor):
    def _create_unique_sql(self, model, fields, name=None, condition=None, *args, **kwargs):
        return super()._create_unique_sql(model, fields, name, filtered_condition(condition), *args, **kwargs)


class DatabaseWrapper(MssqlDatabaseWrapper):
    SchemaEditorClass = DatabaseSchemaEditor
