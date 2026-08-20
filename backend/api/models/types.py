"""Portable column types: native Postgres types in production, JSON/CHAR on SQLite."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import CHAR, JSON, Text, TypeDecorator
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID


class GUID(TypeDecorator):
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PGUUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: Any, dialect) -> Any:
        if value is None:
            return None
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        return value if dialect.name == "postgresql" else str(value)

    def process_result_value(self, value: Any, dialect) -> uuid.UUID | None:
        if value is None:
            return None
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class JSONDict(TypeDecorator):
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Any, dialect) -> Any:
        return {} if value is None else value


class StringArray(TypeDecorator):
    """TEXT[] on Postgres, JSON array elsewhere. Always reads back as list[str]."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(Text()))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Any, dialect) -> list[str]:
        if value is None:
            return []
        return [str(item) for item in value]

    def process_result_value(self, value: Any, dialect) -> list[str]:
        return list(value) if value else []


class FloatArray(TypeDecorator):
    """Embedding storage for the SQL-backed vector store."""

    impl = JSON
    cache_ok = True

    def process_bind_param(self, value: Any, dialect) -> list[float]:
        if value is None:
            return []
        return [float(item) for item in value]

    def process_result_value(self, value: Any, dialect) -> list[float]:
        return [float(item) for item in value] if value else []
