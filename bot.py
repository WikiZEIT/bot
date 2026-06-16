#!/usr/bin/env python
#
# WikiZEIT Bot — pywikibot-based bot for the Polish Wikipedia.
# Copyright (C) 2026 Jakub T. Jankiewicz <https://jakub.jankiewicz.org/>
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU Affero General Public License for more
# details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

import os
import re
import pywikibot
from pywikibot.data import api

DEBUG = False
DEBUG_DIR = 'pages'

MENTEES_PER_PAGE = 400
PAGE_INDEX_WIDTH = 5
SUBPAGE_PREFIX = "{{Wikipedysta:WikiZEITBot/szablon/strona}}"

TEMPLATE_RE = re.compile(
    r"\{\{(?:Wikipedysta|User):WikiZEITBot/szablon\s*\|([^}]+)\}\}",
    flags=re.I,
)

def parse_params(params_str):
    params = {}
    for part in params_str.split('|'):
        if '=' not in part:
            continue
        key, value = part.split('=', 1)
        params[key.strip()] = value.strip()
    return params


def fetch_mentees(site, mentor):
    request = api.Request(
        site=site,
        parameters={
            'action': 'query',
            'list': 'growthmentormentee',
            'gemmmentor': mentor,
        },
    )
    data = request.submit()
    return data.get('growthmentormentee', {}).get('mentees', [])


def fetch_user_info(site, names):
    info = {}
    for i in range(0, len(names), 50):
        chunk = names[i:i + 50]
        request = api.Request(
            site=site,
            parameters={
                'action': 'query',
                'list': 'users',
                'ususers': '|'.join(chunk),
                'usprop': 'editcount|blockinfo|groups',
            },
        )
        data = request.submit()
        for u in data.get('query', {}).get('users', []):
            info[u['name']] = {
                'editcount': u.get('editcount', 0),
                'blocked': 'blockid' in u,
                'groups': set(u.get('groups', [])),
            }
    return info


EXCLUDED_GROUPS = {'editor', 'sysop'}


def is_eligible(name, info):
    u = info.get(name, {})
    if u.get('blocked'):
        return False
    if u.get('groups', set()) & EXCLUDED_GROUPS:
        return False
    return True


MENTEE_TEMPLATE = """=== [[User:<user>|<user>]] ([[User talk:<user>|dyskusja]] <small>•</small> [[Specjalna:Wkład/<user>|edycje]] <small>•</small> [[Specjalna:Rejestr/<user>|rejestr]]) ===
<div>
{{Specjalna:Wkład/<user>|limit=5}}
</div>"""


def render_mentees(mentees):
    return "\n".join(MENTEE_TEMPLATE.replace('<user>', m['name']) for m in mentees)


def format_index(index):
    return f"{index:0{PAGE_INDEX_WIDTH}d}"


def persist(page, text, summary, index):
    if DEBUG:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        path = os.path.join(DEBUG_DIR, format_index(index))
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
        pywikibot.output(f"[DEBUG] zapisano {path}")
        return True
    if page.exists() and page.text == text:
        return False
    page.text = text
    page.save(summary=summary, minor=True)
    return True


def save_subpage(site, parent_title, index, mentees, mentor):
    page = pywikibot.Page(site, f"{parent_title}/{format_index(index)}")
    new_text = f"{SUBPAGE_PREFIX}\n{render_mentees(mentees)}"
    persist(page, new_text, f"[WikiZEIT Test] Strona {index} podopiecznych dla {mentor}", index)


class InvalidDataError(Exception):
    def __init__(self, message: str, error_code: int):
        super().__init__(message)
        self.message = message

    def __str__(self):
        return f"[Kod {self.error_code}]: {self.message}"


def get_menties(site, mentor):
    mentees = fetch_mentees(site, mentor)
    if not mentees:
        raise InvalidDataError("brak podopiecznych")

    info = fetch_user_info(site, [m['name'] for m in mentees])
    mentees = [m for m in mentees if is_eligible(m['name'], info)]
    mentees.sort(key=lambda m: info.get(m['name'], {}).get('editcount', 0), reverse=True)

    chunks = [mentees[i:i + MENTEES_PER_PAGE] for i in range(0, len(mentees), MENTEES_PER_PAGE)]
    if not chunks:
        raise InvalidDataError("brak podopiecznych")

    return chunks


def action_podopieczni(template, akcja, site, params, page):
    mentor = params.get('user')
    if not mentor:
        result = "brak parametru: user"
    else:
        try:
            chunks = get_menties(site, mentor)
            result = render_mentees(chunks[0])
        except InvalidDataError as e:
            result = e.message

    new_text = f"{template}\n<!-- Wynik działania Bota -->\n{result}"

    if persist(page, new_text, f"[WikiZEIT Test] Aktualizacja: akcja={akcja}", 1):
        pywikibot.output(f"Sukces! Strona {page.title()} wykonana akcja {akcja}, parametry: {params}")

    parent_title = page.title()
    for index, batch in enumerate(chunks[1:], start=2):
        save_subpage(site, parent_title, index, batch, mentor)


ACTIONS = {
    'podopieczni': action_podopieczni,
}


def main():
    site = pywikibot.Site('pl', 'wikipedia')
    cat = pywikibot.Category(site, 'Kategoria:Strony monitorowane przez bota WikiZEIT')

    for page in cat.articles():
        if not page.exists():
            continue

        pywikibot.output(f"Przetwarzam stronę: {page.title()}")
        try:
            text = page.text

            m = TEMPLATE_RE.search(text)
            if not m:
                continue

            params = parse_params(m.group(1))
            akcja = params.get('akcja', '').lower()

            handler = ACTIONS.get(akcja)
            if handler is None:
                pywikibot.output(f"Nieznana akcja: {akcja!r}")
                continue

            handler(m.group(0), akcja, site, params, page)
        except Exception as exc:
            pywikibot.error(f"Błąd przy stronie {page.title()}: {exc}")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
