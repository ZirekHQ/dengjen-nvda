# coding: utf-8
"""
Smoke tests for components.py against real wxPython: ImmutableObjectListView
actually populates a wx.ListCtrl from ColumnDefns, get_selected maps the
focused row back to the source object, and every row mutator raises rather
than mutating unless set_objects is holding the guard open.

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

    @pytest.mark.parametrize(
        "mutate",
        [
            pytest.param(lambda v: v.InsertItem(0, "smuggled"), id="InsertItem"),
            pytest.param(lambda v: v.Append(["smuggled", "High"]), id="Append"),
            pytest.param(lambda v: v.DeleteItem(0), id="DeleteItem"),
            pytest.param(lambda v: v.DeleteAllItems(), id="DeleteAllItems"),
            pytest.param(lambda v: v.ClearAll(), id="ClearAll"),
        ],
    )
    def test_row_mutators_raise_and_leave_the_list_untouched(self, list_view, mutate):
        list_view.set_objects([_Row("amy", "medium"), _Row("ryan", "high")])
        with pytest.raises(RuntimeError, match="List is immutable"):
            mutate(list_view)
        assert list_view.ItemCount == 2
        assert list_view.GetItemText(0, 0) == "amy"
        # ClearAll drops the columns too, so a guard that let it through would
        # show up here rather than in the row assertions.
        assert list_view.GetColumnCount() == 2

    def test_the_guard_re_arms_after_set_objects(self, list_view):
        list_view.set_objects([_Row("amy", "medium")])
        assert list_view.ItemCount == 1
        with pytest.raises(RuntimeError, match="List is immutable"):
            list_view.DeleteAllItems()

    def test_the_guard_re_arms_when_set_objects_raises(self, list_view):
        class _Exploding:
            name = "amy"

            @property
            def quality(self):
                raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            list_view.set_objects([_Exploding()])
        # The failure happened inside __unsafe_modify. Without try/finally the
        # flag stays set and the list is writable from then on.
        with pytest.raises(RuntimeError, match="List is immutable"):
            list_view.DeleteAllItems()

    def test_set_focused_item_past_the_end_is_a_no_op(self, list_view):
        list_view.set_objects([_Row("amy", "medium")], set_focus=False)
        assert list_view.GetFocusedItem() == wx.NOT_FOUND
        list_view.set_focused_item(99)
        assert list_view.GetFocusedItem() == wx.NOT_FOUND
        # positive control: without it, a set_focused_item that did nothing
        # at all would also pass the assertions above.
        list_view.set_focused_item(0)
        assert list_view.GetFocusedItem() == 0
