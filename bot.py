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
from datetime import datetime, timedelta, timezone

import pywikibot
from pywikibot.data import api

DEBUG = False
DEBUG_DIR = 'pages'

USE_SQL = True
LAST_EDIT_CUTOFF_DAYS = 365

REPLICA_HOST = 'plwiki.analytics.db.svc.wikimedia.cloud'
REPLICA_DB = 'plwiki_p'
REPLICA_CNF = os.path.expanduser('~/replica.my.cnf')

MENTEES_PER_PAGE = 200
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
                'last_edit': None,
            }
    return info


def fetch_user_info_sql(names):
    if not names:
        return {}

    import pymysql
    import pymysql.cursors

    db_names = [n.replace(' ', '_').encode('utf-8') for n in names]
    placeholders = ', '.join(['%s'] * len(db_names))

    info = {}
    conn = pymysql.connect(
        read_default_file=REPLICA_CNF,
        host=REPLICA_HOST,
        database=REPLICA_DB,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"""
                SELECT
                    u.user_id,
                    u.user_name,
                    u.user_editcount,
                    EXISTS(SELECT 1 FROM block bl
                           JOIN block_target bt ON bt.bt_id = bl.bl_target
                           WHERE bt.bt_user = u.user_id) AS blocked,
                    (SELECT GROUP_CONCAT(ug_group SEPARATOR ',')
                     FROM user_groups WHERE ug_user = u.user_id) AS groups_cat
                FROM user u
                WHERE u.user_name IN ({placeholders})
            """, db_names)

            user_ids = {}
            for row in cursor.fetchall():
                name = row['user_name'].decode('utf-8').replace('_', ' ')
                groups_cat = row['groups_cat']
                groups_str = groups_cat.decode('utf-8') if groups_cat else ''
                info[name] = {
                    'editcount': row['user_editcount'] or 0,
                    'blocked': bool(row['blocked']),
                    'groups': set(groups_str.split(',')) if groups_str else set(),
                    'last_edit': None,
                }
                user_ids[row['user_id']] = name

            if user_ids:
                id_placeholders = ', '.join(['%s'] * len(user_ids))
                cursor.execute(f"""
                    SELECT a.actor_user AS user_id, MAX(r.rev_timestamp) AS last_edit
                    FROM actor a
                    JOIN revision_userindex r ON r.rev_actor = a.actor_id
                    WHERE a.actor_user IN ({id_placeholders})
                    GROUP BY a.actor_user
                """, list(user_ids.keys()))

                for row in cursor.fetchall():
                    name = user_ids.get(row['user_id'])
                    last_edit = row['last_edit']
                    if not name or last_edit is None:
                        continue
                    info[name]['last_edit'] = (
                        last_edit.decode('utf-8') if isinstance(last_edit, bytes) else last_edit
                    )
    finally:
        conn.close()

    return info


def get_user_info(site, names):
    if USE_SQL:
        return fetch_user_info_sql(names)
    return fetch_user_info(site, names)


EXCLUDED_GROUPS = {'editor', 'sysop'}


def is_eligible(name, info):
    u = info.get(name, {})
    if u.get('blocked'):
        return False
    if u.get('groups', set()) & EXCLUDED_GROUPS:
        return False
    return True


MENTEE_TEMPLATE = """=== <span class="plainlinks">[https://pl.wikipedia.org/wiki/User:<user> <user>]</span> ([[User talk:<user>|dyskusja]] <small>•</small> [[Specjalna:Wkład/<user>|edycje]] <small>•</small> [[Specjalna:Rejestr/<user>|rejestr]]) ===
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

    info = get_user_info(site, [m['name'] for m in mentees])
    mentees = [m for m in mentees if is_eligible(m['name'], info)]

    if USE_SQL:
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(days=LAST_EDIT_CUTOFF_DAYS)).strftime('%Y%m%d%H%M%S')
        mentees = [m for m in mentees
                   if (info.get(m['name'], {}).get('last_edit') or '') >= cutoff]
        mentees.sort(key=lambda m: info[m['name']]['last_edit'], reverse=True)
    else:
        mentees.sort(key=lambda m: info.get(m['name'], {}).get('editcount', 0), reverse=True)

    chunks = [mentees[i:i + MENTEES_PER_PAGE] for i in range(0, len(mentees), MENTEES_PER_PAGE)]
    if not chunks:
        raise InvalidDataError("brak podopiecznych")

    return chunks


def action_podopieczni(template, akcja, site, params, page):
    mentor = params.get('user')
    chunks = []
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
        try:
            save_subpage(site, parent_title, index, batch, mentor)
        except Exception as exc:
            pywikibot.error(f"Błąd przy podstronie {parent_title}/{format_index(index)}: {exc}")


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
