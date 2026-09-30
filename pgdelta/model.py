from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Column:
    name: str
    type: str
    nullable: bool
    default: str | None


@dataclass
class Index:
    name: str
    unique: bool
    definition: str


@dataclass
class ForeignKey:
    name: str
    definition: str


@dataclass
class Check:
    name: str
    definition: str


@dataclass
class Table:
    name: str
    columns: dict[str, Column] = field(default_factory=dict)
    primary_key: list[str] = field(default_factory=list)
    primary_key_name: str | None = None
    indexes: dict[str, Index] = field(default_factory=dict)
    foreign_keys: dict[str, ForeignKey] = field(default_factory=dict)
    checks: dict[str, Check] = field(default_factory=dict)


@dataclass
class Schema:
    name: str
    tables: dict[str, Table] = field(default_factory=dict)
