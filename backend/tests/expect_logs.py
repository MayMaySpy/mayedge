"""Mark a test that makes the desk log a warning on purpose.

The warning is captured and must happen, so it stays out of the test output and
any warning left in the output is one nobody expected.
"""

from __future__ import annotations

import functools
import inspect
import unittest
from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def expects_logs(logger: str = "mayedge", level: str = "WARNING") -> Callable[[F], F]:
    def wrap(fn: F) -> F:
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def run_async(self: unittest.TestCase, *args: Any, **kwargs: Any) -> Any:
                with self.assertLogs(logger, level=level):
                    return await fn(self, *args, **kwargs)

            return run_async  # type: ignore[return-value]

        @functools.wraps(fn)
        def run(self: unittest.TestCase, *args: Any, **kwargs: Any) -> Any:
            with self.assertLogs(logger, level=level):
                return fn(self, *args, **kwargs)

        return run  # type: ignore[return-value]

    return wrap
