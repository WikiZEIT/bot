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

import re

import pywikibot

from handlers import PageWrite, TemplateHandler


SOURCE_PAGE = 'Wikiprojekt:Fotografia/Uczestnicy'

# Matches the first user link in a table row, e.g. `[[user:CLI|CLI]]` or
# `[[Wikipedysta:Czupirek|czupirek]]`. Commons cross-wiki links like
# `[[:w:commons:User:CLI/Gallery|...]]` don't match because they start with
# `[[:` not `[[user`/`[[Wikipedysta`.
USER_LINK_RE = re.compile(r'\[\[(?:user|Wikipedysta):([^|\]]+)', flags=re.I)

# Splits the wikitable into rows.
ROW_SEP_RE = re.compile(r'\n\|-')

# Placeholder gallery; real Commons uploads will replace this later.
USER_TEMPLATE = """=== <span class="plainlinks">[https://pl.wikipedia.org/wiki/User:<user> <user>]</span> ===
<gallery>
File:Red-headed weaver (Anaplectes rubriceps leuconotus) male.jpg
File:St. Bonifatius, Wiesbaden, Choir 20200613 6.jpg
File:Po dešti ve Středohoří.jpg
</gallery>"""


def fetch_photographers(site):
    """Read SOURCE_PAGE, extract the first user link per table row, dedupe."""
    page = pywikibot.Page(site, SOURCE_PAGE)
    text = page.text

    users = []
    seen = set()
    for row in ROW_SEP_RE.split(text):
        m = USER_LINK_RE.search(row)
        if not m:
            continue
        name = m.group(1).strip().replace('_', ' ')
        if not name or name in seen:
            continue
        seen.add(name)
        users.append(name)
    return users


class FotografiaHandler(TemplateHandler):
    template_name = "fotografia"

    def handle(self, site, page, params, template_text, new_only=False):
        users = fetch_photographers(site)
        rendered = "\n".join(USER_TEMPLATE.replace('<user>', u) for u in users)
        body = f"{template_text}\n<!-- Wynik działania Bota -->\n{rendered}"
        return [PageWrite(
            index=1,
            body=body,
            summary=f"[WikiZEIT] Aktualizacja: {self.template_name}",
            scope=self.template_name,
        )], None
