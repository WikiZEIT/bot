# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jakub T. Jankiewicz <https://jakub.jankiewicz.org/>

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

    def handle(self, site, page, params, template_text):
        raise NotImplementedError


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

    def handle(self, site, page, params, template_text):
        items = self.fetch_items(site, params)
        chunks = [items[i:i + self.items_per_page]
                  for i in range(0, len(items), self.items_per_page)]
        scope = self.scope(params)

        if not chunks:
            return [PageWrite(
                index=1,
                body=f"{template_text}\n<!-- brak wyników -->",
                summary=f"[WikiZEIT] {self.template_name}: brak wyników",
                scope=scope,
            )]

        writes = [PageWrite(
            index=1,
            body=f"{template_text}\n<!-- Wynik działania Bota -->\n{self.render_chunk(chunks[0], params)}",
            summary=f"[WikiZEIT] Aktualizacja: {self.template_name}",
            scope=scope,
        )]
        for idx, batch in enumerate(chunks[1:], start=2):
            writes.append(PageWrite(
                index=idx,
                body=f"{self.subpage_prefix}\n{self.render_chunk(batch, params)}",
                summary=f"[WikiZEIT] {self.template_name}: strona {idx}",
                scope=scope,
            ))
        return writes


class NoOpHandler(TemplateHandler):
    template_name = "Wikipedysta:WikiZEITBot/szablon"

    def handle(self, site, page, params, template_text):
        return []
