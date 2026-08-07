# coding: utf-8
"""
Contract tests for components.py that are not about a specific widget:
AsyncSnakDialog's done-callback protocol, and a sweep proving every
annotation in the module names something that actually exists.

The sweep is the general net for a bug class this module has hit twice --
#86 (`t.Union`) and #88 (`DoneCallback`) were both names that did not exist,
kept invisible by `from __future__ import annotations`.
"""

import inspect
import sys
import typing
from concurrent.futures import Future

import pytest

if sys.platform != "win32":
    # A skipif marker is not enough: pytest imports the module during
    # collection, and `import wx` fails outright without a Windows wheel.
    pytest.skip("real wxPython is Windows-only here", allow_module_level=True)


@pytest.fixture
def components(gui_plugin_package):
    from dengjen_tts_global_plugin import components

    return components


class _PendingExecutor:
    """Hands back a Future that is still pending, like a real thread pool
    would. An already-settled one fires the done-callback -- and so destroys
    the dialog -- partway through AsyncSnakDialog.__init__, which then trips
    over its own CenterOnScreen call."""

    def __init__(self):
        self.future = Future()

    def submit(self, func, *args, **kwargs):
        return self.future


def _as_function(obj):
    if isinstance(obj, property):
        obj = obj.fget
    elif isinstance(obj, (staticmethod, classmethod)):
        obj = obj.__func__
    if inspect.isfunction(obj):
        yield obj


def _annotatable(module):
    """Everything defined in `module` that can carry an annotation: its own
    classes (where the class body itself annotates something), their methods
    and property getters, and its module-level functions."""
    for obj in vars(module).values():
        if getattr(obj, "__module__", None) != module.__name__:
            continue
        if inspect.isclass(obj):
            if "__annotations__" in vars(obj):
                yield obj
            for member in vars(obj).values():
                yield from _as_function(member)
        else:
            yield from _as_function(obj)


def test_every_annotation_in_components_resolves(components):
    swept = list(_annotatable(components))
    # positive control: an empty or mis-filtered sweep would pass vacuously.
    assert {"ColumnDefn", "AsyncSnakDialog.__init__"} <= {o.__qualname__ for o in swept}

    unresolvable = {}
    for obj in swept:
        try:
            typing.get_type_hints(obj)
        except NameError as exc:
            unresolvable[obj.__qualname__] = str(exc)
    assert not unresolvable


class TestAsyncSnakDialog:
    def test_done_callback_receives_the_completed_future(self, components):
        # __init__ needs a real dialog and a live executor; the callback path
        # needs neither. snak_dg=None makes the real dismiss() a no-op, so
        # nothing here is stubbed -- on_future_completed and dismiss both run.
        dialog = components.AsyncSnakDialog.__new__(components.AsyncSnakDialog)
        dialog.snak_dg = None
        received = []
        dialog.done_callback = received.append

        future = Future()
        future.set_result("voices")
        dialog.on_future_completed(future)

        # This is what DoneCallback annotates: the Future itself, not its
        # result. voice_manager's callback calls .result() on what it gets.
        assert received == [future]
        assert received[0].result() == "voices"

    def test_future_is_the_submitted_future_and_stays_wired(
        self, components, nvda_gui
    ):
        executor = _PendingExecutor()
        received = []
        dialog = components.AsyncSnakDialog(
            executor=executor,
            func=lambda: "voices",
            done_callback=received.append,
            parent=nvda_gui,
            message="Retrieving voices list. Please wait...",
        )

        # add_done_callback returns None, so assigning its result left this
        # attribute permanently None (#94).
        assert dialog.future is executor.future
        assert not received

        # Splitting that call must not cost the callback: settling the future
        # still has to reach done_callback through the real constructor.
        executor.future.set_result("voices")
        assert received == [executor.future]
