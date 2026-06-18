# Copyright (C) 2026 Jakub T. Jankiewicz <https://jakub.jankiewicz.org/>
#
# This file is part of WikiZEIT Bot.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

from dataclasses import dataclass
from typing import Optional


@dataclass
class PageWrite:
    index: int
    body: str
    summary: str
    scope: Optional[str] = None  # used as subdirectory in DEBUG file output


class TemplateHandler:
    template_name: str = ""

    def handle(self, site, page, params, template_text, new_only=False):
        """Returns (writes, commit) where commit is None or a no-argument callable
        that the controller invokes only after every write succeeds."""
        raise NotImplementedError

    def migrate(self, site, page, params, template_text):
        """Populate any persistent state from the current wiki state without
        producing writes. Default no-op for stateless handlers."""
        return


class PaginatedHandler(TemplateHandler):
    items_per_page: int = 200
    subpage_prefix: str = ""

    def fetch_items(self, site, params):
        raise NotImplementedError

    def render_item(self, item, params):
        raise NotImplementedError

    def render_chunk(self, items, params):
        return "\n".join(self.render_item(i, params) for i in items)

    def scope(self, params):
        return None

    def get_items_per_page(self, params):
        return self.items_per_page

    def get_subpage_prefix(self, params):
        return self.subpage_prefix

    def build_writes(self, items, params, template_text):
        per_page = self.get_items_per_page(params)
        chunks = [items[i:i + per_page]
                  for i in range(0, len(items), per_page)]
        scope = self.scope(params)

        if not chunks:
            return [PageWrite(
                index=1,
                body=f"{template_text}\n<!-- brak wyników -->",
                summary=f"[WikiZEIT] {self.template_name}: brak wyników",
                scope=scope,
            )]

        prefix = self.get_subpage_prefix(params)
        writes = [PageWrite(
            index=1,
            body=f"{template_text}\n<!-- Wynik działania Bota -->\n{self.render_chunk(chunks[0], params)}",
            summary=f"[WikiZEIT] Aktualizacja: {self.template_name}",
            scope=scope,
        )]
        for idx, batch in enumerate(chunks[1:], start=2):
            writes.append(PageWrite(
                index=idx,
                body=f"{prefix}\n{self.render_chunk(batch, params)}",
                summary=f"[WikiZEIT] {self.template_name}: strona {idx}",
                scope=scope,
            ))
        return writes

    def handle(self, site, page, params, template_text, new_only=False):
        items = self.fetch_items(site, params)
        return self.build_writes(items, params, template_text), None


class SzablonHandler(TemplateHandler):
    """Dispatcher for {{Wikipedysta:WikiZEITBot/szablon|akcja=<x>}}.

    Sub-handlers register themselves keyed by `akcja` value. Unrecognized or
    missing `akcja` produces no writes — the page stays untouched.
    """

    template_name = "Wikipedysta:WikiZEITBot/szablon"

    def __init__(self):
        self.sub_handlers = {}

    def _sub(self, params):
        return self.sub_handlers.get(params.get('akcja', '').lower())

    def handle(self, site, page, params, template_text, new_only=False):
        sub = self._sub(params)
        if sub is None:
            return [], None
        return sub.handle(site, page, params, template_text, new_only=new_only)

    def migrate(self, site, page, params, template_text):
        sub = self._sub(params)
        if sub is not None:
            sub.migrate(site, page, params, template_text)
