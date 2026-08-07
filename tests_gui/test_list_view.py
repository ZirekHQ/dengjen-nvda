# coding: utf-8
"""
Smoke tests for components.py against real wxPython: ImmutableObjectListView
actually populates a wx.ListCtrl from ColumnDefns, get_selected maps the
focused row back to the source object, and the EVT_LIST_INSERT_ITEM /
EVT_LIST_DELETE_ITEM bindings reach the immutability guard. wx swallows the
RuntimeError those handlers raise, though, so the guard never actually blocks
a mutation -- it only logs one to stderr.

These assert wiring, not decisions -- the wx-free decisions live in
voice_manager_logic.py and are covered on both CI legs by
tests/test_voice_manager_logic.py.
"""

import sys
import typing

import pytest

if sys.platform != "win32":
    # A skipif marker is not enough: pytest imports the module during
    # collection, and `import wx` fails outright without a Windows wheel.
    pytest.skip("real wxPython is Windows-only here", allow_module_level=True)

import wx


class _Row:
    def __init__(self, name, quality):
        self.name = name
        self.quality = quality


@pytest.fixture
def components(gui_plugin_package):
    from dengjen_tts_global_plugin import components

    return components


@pytest.fixture
def list_view(components, nvda_gui):
    """A real ImmutableObjectListView with one attribute-name column and one
    callable column -- ColumnDefn accepts either form."""
    view = components.ImmutableObjectListView(
        nvda_gui,
        -1,
        columns=[
            components.ColumnDefn("Name", "left", 30, "name"),
            components.ColumnDefn("Quality", "center", 30, lambda r: r.quality.title()),
        ],
    )
    yield view
    view.Destroy()


class TestColumnDefn:
    def test_alignment_maps_to_wx_format_flags(self, components):
        assert components.ColumnDefn("t", "left", 1, "x").alignment_flag == wx.LIST_FORMAT_LEFT
        assert components.ColumnDefn("t", "center", 1, "x").alignment_flag == wx.LIST_FORMAT_CENTRE
        assert components.ColumnDefn("t", "right", 1, "x").alignment_flag == wx.LIST_FORMAT_RIGHT

    def test_unknown_alignment_is_rejected(self, components):
        with pytest.raises(ValueError, match="Unknown alignment directive"):
            components.ColumnDefn("t", "sideways", 1, "x").alignment_flag

    def test_annotations_resolve(self, components):
        # `from __future__ import annotations` keeps these as strings, so a
        # typo in an annotation never raises at import -- only here.
        hints = typing.get_type_hints(components.ColumnDefn)
        assert "string_converter" in hints


class TestImmutableObjectListView:
    def test_columns_are_created_from_the_definitions(self, list_view):
        assert list_view.GetColumnCount() == 2

    def test_objects_populate_rows_via_both_converter_forms(self, list_view):
        list_view.set_objects([_Row("amy", "medium"), _Row("ryan", "high")])
        assert list_view.ItemCount == 2
        assert list_view.GetItemText(0, 0) == "amy"
        assert list_view.GetItemText(0, 1) == "Medium"
        assert list_view.GetItemText(1, 1) == "High"

    def test_set_objects_replaces_rather_than_appends(self, list_view):
        list_view.set_objects([_Row("amy", "medium")])
        list_view.set_objects([_Row("ryan", "high")])
        assert list_view.ItemCount == 1
        assert list_view.GetItemText(0, 0) == "ryan"

    def test_get_selected_returns_the_focused_source_object(self, list_view):
        rows = [_Row("amy", "medium"), _Row("ryan", "high")]
        list_view.set_objects(rows)
        list_view.set_focused_item(1)
        assert list_view.get_selected() is rows[1]

    def test_get_selected_is_none_when_the_list_is_empty(self, list_view):
        list_view.set_objects([])
        assert list_view.get_selected() is None

    def test_mutation_guard_raises_outside_set_objects(self, list_view):
        # Not asserted via InsertItem: wx swallows exceptions raised inside
        # event handlers, so onInsertItem's RuntimeError reaches stderr but
        # never propagates to the caller -- pytest.raises would see nothing.
        with pytest.raises(RuntimeError, match="List is immutable"):
            list_view.prevent_mutations()

    def test_insert_item_reaches_the_mutation_guard_through_the_binding(
        self, list_view, monkeypatch
    ):
        calls = []
        monkeypatch.setattr(list_view, "prevent_mutations", lambda: calls.append(1))
        list_view.InsertItem(0, "smuggled")
        assert calls  # the EVT_LIST_INSERT_ITEM binding reached the guard

    def test_set_objects_leaves_the_mutation_guard_armed_afterwards(self, list_view):
        # prevent_mutations() IS called by onInsertItem during set_objects's
        # own Append calls -- it just doesn't raise, because __unsafe_modify
        # holds the guard open for exactly that duration. So "does the guard
        # fire during set_objects" isn't a real question; what set_objects
        # must not do is leave the guard permanently disarmed afterwards.
        with pytest.raises(RuntimeError, match="List is immutable"):
            list_view.prevent_mutations()
        list_view.set_objects([_Row("amy", "medium")])
        assert list_view.ItemCount == 1
        with pytest.raises(RuntimeError, match="List is immutable"):
            list_view.prevent_mutations()

    def test_set_focused_item_past_the_end_is_a_no_op(self, list_view):
        list_view.set_objects([_Row("amy", "medium")], set_focus=False)
        assert list_view.GetFocusedItem() == wx.NOT_FOUND
        list_view.set_focused_item(99)
        assert list_view.GetFocusedItem() == wx.NOT_FOUND
        # positive control: without it, a set_focused_item that did nothing
        # at all would also pass the assertions above.
        list_view.set_focused_item(0)
        assert list_view.GetFocusedItem() == 0
