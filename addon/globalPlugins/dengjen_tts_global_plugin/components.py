# Copyright (c) 2023 Musharraf Omer
# This file is covered by the GNU General Public License.

from __future__ import annotations

import contextlib
import dataclasses
import typing
from concurrent.futures import Future

import addonHandler
import gui
import wx
import wx.lib.mixins.listctrl as listmix

from . import sized_controls as sc

addonHandler.initTranslation()


ObjectCollection = typing.Iterable[typing.Any]
DoneCallback = typing.Callable[[Future], None]


def make_sized_static_box(parent, title):
    stbx = sc.SizedStaticBox(parent, -1, title)
    stbx.SetSizerProp("expand", True)
    stbx.Sizer.AddSpacer(25)
    return stbx


class DialogListCtrl(wx.ListCtrl, listmix.ListCtrlAutoWidthMixin):
    def __init__(
        self,
        parent,
        id,
        pos=wx.DefaultPosition,
        size=wx.DefaultSize,
        # No LC_EDIT_LABELS: the only subclass is ImmutableObjectListView, and
        # in-place label editing rewrites a row behind self._objects' back.
        style=wx.BORDER_SUNKEN | wx.LC_SINGLE_SEL | wx.LC_REPORT | wx.LC_VRULES,
    ):
        wx.ListCtrl.__init__(self, parent, id, pos, size, style)
        listmix.ListCtrlAutoWidthMixin.__init__(self)

    def set_focused_item(self, idx: int):
        if idx >= self.ItemCount:
            return
        self.SetFocus()
        self.EnsureVisible(idx)
        self.Select(idx)
        self.SetItemState(idx, wx.LIST_STATE_FOCUSED, wx.LIST_STATE_FOCUSED)


class SimpleDialog(sc.SizedDialog):
    """Basic dialog for simple  GUI forms."""

    def __init__(self, parent, title, style=wx.DEFAULT_DIALOG_STYLE, **kwargs):
        super().__init__(parent, title=title, style=style, **kwargs)
        self.parent = parent

        panel = self.GetContentsPane()
        self.addControls(panel)
        buttons_sizer = self.getButtons(panel)
        if buttons_sizer is not None:
            self.SetButtonSizer(buttons_sizer)

        self.Layout()
        self.Fit()
        self.SetMinSize(self.GetSize())
        self.Center(wx.BOTH)

    def SetButtonSizer(self, sizer):
        bottom_sizer = wx.BoxSizer(wx.VERTICAL)
        line = wx.StaticLine(self, -1, size=(20, -1), style=wx.LI_HORIZONTAL)
        bottom_sizer.Add(line, 0, wx.TOP | wx.EXPAND, 15)
        bottom_sizer.Add(sizer, 0, wx.EXPAND | wx.ALL, 10)
        super().SetButtonSizer(bottom_sizer)

    def addControls(self, parent):
        raise NotImplementedError

    def getButtons(self, parent):
        btnsizer = wx.StdDialogButtonSizer()
        # Translators: the label of the OK button in a dialog
        ok_btn = wx.Button(self, wx.ID_OK, _("OK"))
        ok_btn.SetDefault()
        # Translators: the label of the cancel button in a dialog
        cancel_btn = wx.Button(self, wx.ID_CANCEL, _("Cancel"))
        for btn in (ok_btn, cancel_btn):
            btnsizer.AddButton(btn)
        btnsizer.Realize()
        return btnsizer


class SnakDialog(SimpleDialog):
    """A Toast style notification  dialog for showing a simple message without a title."""

    def __init__(self, message, *args, dismiss_callback=None, **kwargs):
        self.message = message
        self.dismiss_callback = dismiss_callback
        super().__init__(*args, title="", style=0, **kwargs)

    def addControls(self, parent):
        ai = wx.ActivityIndicator(parent)
        ai.SetSizerProp("halign", "center")
        self.staticMessage = wx.StaticText(parent, -1, self.message)
        self.staticMessage.SetFocusFromKbd()
        self.Bind(wx.EVT_CLOSE, self.onClose, self)
        # On the dialog, and EVT_CHAR_HOOK rather than EVT_KEY_UP: the top-level
        # window sees a char hook before the focused child, whereas key events do
        # not propagate at all -- and wxStaticText hard-codes AcceptsFocus() to
        # false, so the message can never hold focus to receive one (#101).
        self.Bind(wx.EVT_CHAR_HOOK, self.onCharHook)
        ai.Start()

    @contextlib.contextmanager
    def ShowBriefly(self):
        try:
            wx.CallAfter(self.Show)
            yield
        finally:
            wx.CallAfter(self.Close)
            wx.CallAfter(self.Destroy)

    def onClose(self, event):
        if event.CanVeto():
            if self.dismiss_callback is not None:
                should_close = self.dismiss_callback()
                if should_close:
                    self.Hide()
                    return
            event.Veto()
        else:
            self.Destroy()

    def onCharHook(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.Close()
            return
        event.Skip()

    def getButtons(self, parent):
        return


class AsyncSnakDialog:
    """A helper to make the use of SnakDialogs Ergonomic."""

    def __init__(
        self,
        executor,
        func,
        done_callback: DoneCallback,
        *sdg_args,
        **sdg_kwargs,
    ):
        self.snak_dg = SnakDialog(*sdg_args, **sdg_kwargs)
        self.done_callback = done_callback
        self.future = executor.submit(func)
        self.future.add_done_callback(self.on_future_completed)
        self.snak_dg.CenterOnScreen()
        gui.runScriptModalDialog(self.snak_dg)

    def on_future_completed(self, completed_future):
        self.dismiss()
        wx.CallAfter(self.done_callback, completed_future)

    def dismiss(self):
        if self.snak_dg:
            wx.CallAfter(self.snak_dg.Hide)
            wx.CallAfter(self.snak_dg.Close)
            wx.CallAfter(self.snak_dg.Destroy)


@dataclasses.dataclass
class ColumnDefn:
    title: str
    alignment: str
    width: int
    string_converter: typing.Callable[[typing.Any], str] | str

    _ALIGNMENT_FLAGS = {
        "left": wx.LIST_FORMAT_LEFT,
        "center": wx.LIST_FORMAT_CENTRE,
        "right": wx.LIST_FORMAT_RIGHT,
    }

    @property
    def alignment_flag(self):
        flag = self._ALIGNMENT_FLAGS.get(self.alignment)
        if flag is not None:
            return flag
        raise ValueError(f"Unknown alignment directive {self.alignment}")


class ImmutableObjectListView(DialogListCtrl):
    """An immutable  list view that deals with objects rather than strings."""

    def __init__(
        self,
        *args,
        columns: typing.Iterable[ColumnDefn] = (),
        objects: ObjectCollection = (),
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._objects = None
        self._columns = None
        self.__is_modifying = False
        self.set_columns(columns)
        self.set_objects(objects)

    @contextlib.contextmanager
    def __unsafe_modify(self):
        was_modifying = self.__is_modifying
        self.__is_modifying = True
        try:
            yield
        finally:
            self.__is_modifying = was_modifying

    def set_columns(self, columns):
        with self.__unsafe_modify():
            self.ClearAll()
            self._columns = tuple(columns)
            for col in self._columns:
                self.AppendColumn(col.title, format=col.alignment_flag, width=col.width)
            for i in range(len(self._columns)):
                self.SetColumnWidth(i, 100)

    def set_objects(
        self, objects: ObjectCollection, focus_item: int = 0, set_focus=True
    ):
        """Clear the list view and insert the objects."""
        self._objects = tuple(objects)
        self.set_columns(self._columns)
        string_converters = [c.string_converter for c in self._columns]
        with self.__unsafe_modify():
            for obj in self._objects:
                col_labels = []
                for to_str in string_converters:
                    col_labels.append(
                        getattr(obj, to_str) if not callable(to_str) else to_str(obj)
                    )
                self.Append(col_labels)
        if set_focus:
            self.set_focused_item(focus_item)

    def get_selected(self) -> typing.Any | None:
        """Return the currently selected object or None."""
        idx = self.GetFocusedItem()
        if idx != wx.NOT_FOUND:
            return self._objects[idx]

    def prevent_mutations(self):
        if not self.__is_modifying:
            raise RuntimeError(
                "List is immutable. Use 'ImmutableObjectListView.set_objects' instead"
            )

    # Overriding the row mutators rather than handling EVT_LIST_INSERT_ITEM /
    # EVT_LIST_DELETE_ITEM: those fire after the row is already gone, and wx
    # discards whatever a handler raises (see #87).
    def Append(self, entry):
        self.prevent_mutations()
        return super().Append(entry)

    def InsertItem(self, *args, **kwargs):
        self.prevent_mutations()
        return super().InsertItem(*args, **kwargs)

    def SetItem(self, *args, **kwargs):
        self.prevent_mutations()
        return super().SetItem(*args, **kwargs)

    def DeleteItem(self, item):
        self.prevent_mutations()
        return super().DeleteItem(item)

    def DeleteAllItems(self):
        self.prevent_mutations()
        return super().DeleteAllItems()

    def ClearAll(self):
        self.prevent_mutations()
        return super().ClearAll()

    def EditLabel(self, item, *args, **kwargs):
        self.prevent_mutations()
        return super().EditLabel(item, *args, **kwargs)
