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

import os
from datetime import datetime, timedelta, timezone

import pymysql
import pymysql.cursors
from pywikibot.data import api

from handlers import PageWrite, PaginatedHandler


USE_SQL = True
LAST_EDIT_CUTOFF_DAYS = 365

REPLICA_HOST = 'plwiki.analytics.db.svc.wikimedia.cloud'
REPLICA_DB = 'plwiki_p'
REPLICA_CNF = os.path.expanduser('~/replica.my.cnf')

EXCLUDED_GROUPS = {'editor', 'sysop'}

# Per-mentee wiki block. <user> and <limit> are placeholders substituted via
# str.replace (chosen over .format so the literal {{ / }} need no escaping).
MENTEE_TEMPLATE = """=== <span class="plainlinks">[https://pl.wikipedia.org/wiki/User:<user> <user>]</span> ([[User talk:<user>|dyskusja]] <small>•</small> [[Specjalna:Wkład/<user>|edycje]] <small>•</small> [[Specjalna:Rejestr/<user>|rejestr]]) ===
<div>
{{Specjalna:Wkład/<user>|limit=<limit>}}
</div>"""

DEFAULT_EDYCJE = 5


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


def fetch_user_info_api(site, names):
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
    return fetch_user_info_api(site, names)


def is_eligible(name, info):
    u = info.get(name, {})
    if u.get('blocked'):
        return False
    if u.get('groups', set()) & EXCLUDED_GROUPS:
        return False
    return True


class MenteesHandler(PaginatedHandler):
    template_name = "Podopieczni"
    items_per_page = 200
    subpage_prefix = "{{Podopieczni/strona}}"

    def scope(self, params):
        return params.get('przewodnik')

    def get_items_per_page(self, params):
        raw = params.get('limit')
        try:
            n = int(raw)
            if n > 0:
                return n
        except (TypeError, ValueError):
            pass
        return self.items_per_page

    def handle(self, site, page, params, template_text):
        if not params.get('przewodnik'):
            return [PageWrite(
                index=1,
                body=f"{template_text}\n<!-- brak parametru: przewodnik -->",
                summary=f"[WikiZEIT] {self.template_name}: brak parametru przewodnik",
            )]
        return super().handle(site, page, params, template_text)

    def fetch_items(self, site, params):
        mentor = params['przewodnik']
        mentees = fetch_mentees(site, mentor)
        if not mentees:
            return []

        info = get_user_info(site, [m['name'] for m in mentees])
        mentees = [m for m in mentees if is_eligible(m['name'], info)]

        if USE_SQL:
            cutoff = (datetime.now(timezone.utc)
                      - timedelta(days=LAST_EDIT_CUTOFF_DAYS)).strftime('%Y%m%d%H%M%S')
            mentees = [m for m in mentees
                       if (info.get(m['name'], {}).get('last_edit') or '') >= cutoff]
            mentees.sort(key=lambda m: info[m['name']]['last_edit'], reverse=True)
        else:
            mentees.sort(key=lambda m: info.get(m['name'], {}).get('editcount', 0),
                         reverse=True)

        return mentees

    def render_item(self, mentee, params):
        edycje = params.get('edycje') or DEFAULT_EDYCJE
        try:
            edycje = int(edycje)
        except (TypeError, ValueError):
            edycje = DEFAULT_EDYCJE
        return (MENTEE_TEMPLATE
                .replace('<user>', mentee['name'])
                .replace('<limit>', str(edycje)))
