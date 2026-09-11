"""Algo book protocol — desk iterates registered books instead of naming each type."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AlgoBook(Protocol):
    @property
    def algo_type(self) -> str: ...

    def has(self, algo_id: str) -> bool: ...

    def to_dict(self) -> dict[str, object]: ...

    def on_gateway(self, msg: dict[str, object]) -> None: ...

    async def start_from_body(self, body: dict[str, Any]) -> None: ...

    async def stop(self, algo_id: str | None = None) -> None: ...

    async def pause(self, algo_id: str) -> None: ...

    async def unpause(self, algo_id: str) -> None: ...

    async def pause_for_market(self, market_index: int | None) -> None: ...

    async def restore(self) -> None: ...

    async def drain_for_shutdown(self) -> None: ...

    async def flush(self) -> None: ...


def find_book(books: tuple[AlgoBook, ...], algo_type: str) -> AlgoBook | None:
    for book in books:
        if book.algo_type == algo_type:
            return book
    return None


def find_book_by_algo_id(books: tuple[AlgoBook, ...], algo_id: str) -> AlgoBook | None:
    for book in books:
        if book.has(algo_id):
            return book
    return None
