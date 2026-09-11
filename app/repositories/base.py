"""Generic repository with pagination, sorting and filtering helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, func, or_
from sqlalchemy.orm import InstrumentedAttribute

from app.errors import NotFoundError
from app.extensions import db

T = TypeVar("T")


@dataclass
class Page(Generic[T]):
    items: list[T]
    total: int
    page: int
    per_page: int
    filters: dict[str, Any] = field(default_factory=dict)

    @property
    def pages(self) -> int:
        return max(1, (self.total + self.per_page - 1) // self.per_page)

    @property
    def has_next(self) -> bool:
        return self.page < self.pages

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    def to_dict(self, serializer=None) -> dict[str, Any]:
        serializer = serializer or (lambda item: item.to_dict())
        return {
            "items": [serializer(item) for item in self.items],
            "pagination": {
                "page": self.page,
                "per_page": self.per_page,
                "total": self.total,
                "pages": self.pages,
                "has_next": self.has_next,
                "has_prev": self.has_prev,
            },
            "filters": self.filters,
        }


class Repository(Generic[T]):
    model: type[T]
    default_sort: str = "id"
    sortable: dict[str, InstrumentedAttribute] = {}
    searchable: list[InstrumentedAttribute] = []

    def __init__(self, session=None) -> None:
        self.session = session or db.session

    # --- basic CRUD ------------------------------------------------------------------
    def get(self, ident: int) -> T | None:
        return self.session.get(self.model, ident)

    def get_or_404(self, ident: int, label: str | None = None) -> T:
        obj = self.get(ident)
        if obj is None:
            raise NotFoundError(f"{label or self.model.__name__} {ident} not found.")
        return obj

    def add(self, obj: T, commit: bool = True) -> T:
        self.session.add(obj)
        if commit:
            self.session.commit()
        else:
            self.session.flush()
        return obj

    def delete(self, obj: T, commit: bool = True) -> None:
        self.session.delete(obj)
        if commit:
            self.session.commit()

    def commit(self) -> None:
        self.session.commit()

    def all(self) -> list[T]:
        return list(self.session.execute(db.select(self.model).order_by(self.model.id)).scalars())

    def count(self, stmt: Select | None = None) -> int:
        stmt = stmt if stmt is not None else db.select(self.model)
        return self.session.execute(db.select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()

    # --- listing ---------------------------------------------------------------------------
    def base_query(self) -> Select:
        return db.select(self.model)

    def apply_search(self, stmt: Select, search: str | None) -> Select:
        if search and self.searchable:
            pattern = f"%{search.strip()}%"
            stmt = stmt.where(or_(*[col.ilike(pattern) for col in self.searchable]))
        return stmt

    def apply_sort(self, stmt: Select, sort: str | None, direction: str | None) -> Select:
        column = self.sortable.get(sort or self.default_sort) or self.sortable.get(self.default_sort) or self.model.id
        if (direction or "desc").lower() == "asc":
            return stmt.order_by(column.asc(), self.model.id.asc())
        return stmt.order_by(column.desc(), self.model.id.desc())

    def paginate(self, stmt: Select, page: int = 1, per_page: int = 25, filters: dict[str, Any] | None = None) -> Page[T]:
        page = max(1, int(page or 1))
        per_page = min(max(1, int(per_page or 25)), 500)
        total = self.count(stmt)
        items = list(self.session.execute(stmt.limit(per_page).offset((page - 1) * per_page)).scalars().unique())
        return Page(items=items, total=total, page=page, per_page=per_page, filters=filters or {})

    def list(self, *, page: int = 1, per_page: int = 25, search: str | None = None, sort: str | None = None, direction: str | None = None, **filters: Any) -> Page[T]:
        stmt = self.base_query()
        stmt = self.apply_filters(stmt, filters)
        stmt = self.apply_search(stmt, search)
        stmt = self.apply_sort(stmt, sort, direction)
        return self.paginate(stmt, page, per_page, {k: v for k, v in filters.items() if v not in (None, "")} | ({"search": search} if search else {}))

    def apply_filters(self, stmt: Select, filters: dict[str, Any]) -> Select:
        for key, value in filters.items():
            if value in (None, ""):
                continue
            column = getattr(self.model, key, None)
            if column is not None:
                stmt = stmt.where(column == value)
        return stmt
