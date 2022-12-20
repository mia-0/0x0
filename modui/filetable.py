from textual.widgets import DataTable, Static
from textual.reactive import Reactive
from textual.message import Message, MessageTarget
from textual import events, log
from jinja2.filters import do_filesizeformat

from fhost import File
from modui import mime

class FileTable(DataTable):
    query = Reactive(None)
    order_col = Reactive(0)
    order_desc = Reactive(True)
    limit = 10000
    colmap = [File.id, File.removed, File.nsfw_score, None, File.ext, File.size, File.mime]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.add_columns("#", "☣️", "🔞", "📂", "name", "size", "mime")
        self.base_query = File.query.filter(File.size != None)
        self.query = self.base_query

    class Selected(Message):
        def __init__(self, sender: MessageTarget, f: File) -> None:
            self.file = f
            super().__init__(sender)

    def watch_order_col(self, old, value) -> None:
        self.watch_query(None, None)

    def watch_order_desc(self, old, value) -> None:
        self.watch_query(None, None)

    def watch_query(self, old, value) -> None:
        def fmt_file(f: File) -> tuple:
            return (
                str(f.id),
                "🔴" if f.removed else "  ",
                "🚩" if f.is_nsfw else "  ",
                "👻" if not f.getpath().is_file() else "  ",
                f.getname(),
                do_filesizeformat(f.size, True),
                f"{mime.mimemoji.get(f.mime.split('/')[0], mime.mimemoji.get(f.mime)) or '  '} " + f.mime,
            )

        if (self.query):
            self.clear()
            order = FileTable.colmap[self.order_col]
            q = self.query
            if order: q = q.order_by(order.desc() if self.order_desc else order, File.id)
            self.add_rows(map(fmt_file, q.limit(self.limit)))

    def _scroll_cursor_in_to_view(self, animate: bool = False) -> None:
        region = self._get_cell_region(self.cursor_row, 0)
        spacing = self._get_cell_border()
        self.scroll_to_region(region, animate=animate, spacing=spacing)

    async def watch_cursor_cell(self, old, value) -> None:
        super().watch_cursor_cell(old, value)
        if value[0] < len(self.data) and value[0] >= 0:
            f = File.query.get(int(self.data[value[0]][0]))
            await self.emit(self.Selected(self, f))

    def on_click(self, event: events.Click) -> None:
        super().on_click(event)
        meta = self.get_style_at(event.x, event.y).meta
        if meta:
            if meta["row"] == -1:
                qi = FileTable.colmap[meta["column"]]
                if meta["column"] == self.order_col:
                    self.order_desc = not self.order_desc
                self.order_col = meta["column"]
