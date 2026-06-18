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
import re

import pymysql
import pymysql.cursors
import pywikibot

from handlers import PageWrite, TemplateHandler


SOURCE_PAGE = 'Wikiprojekt:Fotografia/Uczestnicy'

COMMONS_HOST = 'commonswiki.analytics.db.svc.wikimedia.cloud'
COMMONS_DB = 'commonswiki_p'
REPLICA_CNF = os.path.expanduser('~/replica.my.cnf')

DEFAULT_LIMIT = 10
MAX_LIMIT = 20

# Matches the first user link in a table row, e.g. `[[user:CLI|CLI]]` or
# `[[Wikipedysta:Czupirek|czupirek]]`. Commons cross-wiki links like
# `[[:w:commons:User:CLI/Gallery|...]]` don't match because they start with
# `[[:` not `[[user`/`[[Wikipedysta`.
USER_LINK_RE = re.compile(r'\[\[(?:user|Wikipedysta):([^|\]]+)', flags=re.I)
ROW_SEP_RE = re.compile(r'\n\|-')

USER_TEMPLATE = """=== <span class="plainlinks">[https://pl.wikipedia.org/wiki/User:<user> <user>]</span> ===
<gallery>
<files>
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


def fetch_uploads(users, limit):
    """Return {user: [filenames]} of the `limit` most recent uploads per user
    from the Wikimedia Commons SQL replica, in a single query using
    ROW_NUMBER() OVER (...). Users with no uploads or no Commons account
    simply don't appear in the result."""
    if not users:
        return {}

    db_names = [u.replace(' ', '_').encode('utf-8') for u in users]
    placeholders = ', '.join(['%s'] * len(db_names))

    query = f"""
        SELECT actor_name, img_name FROM (
            SELECT
                a.actor_name,
                i.img_name,
                ROW_NUMBER() OVER (
                    PARTITION BY a.actor_id ORDER BY i.img_timestamp DESC
                ) AS rn
            FROM image i
            JOIN actor a ON a.actor_id = i.img_actor
            WHERE a.actor_name IN ({placeholders})
        ) ranked
        WHERE rn <= %s
        ORDER BY actor_name, rn
    """

    conn = pymysql.connect(
        read_default_file=REPLICA_CNF,
        host=COMMONS_HOST,
        database=COMMONS_DB,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
    )
    result = {}
    try:
        with conn.cursor() as cursor:
            cursor.execute(query, (*db_names, limit))
            for row in cursor.fetchall():
                name = row['actor_name'].decode('utf-8').replace('_', ' ')
                img_name = row['img_name'].decode('utf-8').replace('_', ' ')
                result.setdefault(name, []).append(img_name)
    finally:
        conn.close()
    return result


def render_user(user, files):
    return (USER_TEMPLATE
            .replace('<user>', user)
            .replace('<files>', "\n".join(f"File:{f}" for f in files)))


class FotografiaHandler(TemplateHandler):
    template_name = "Fotografia"

    def handle(self, site, page, params, template_text, new_only=False):
        raw = params.get('limit')
        try:
            limit = int(raw)
            if limit <= 0:
                limit = DEFAULT_LIMIT
        except (TypeError, ValueError):
            limit = DEFAULT_LIMIT
        limit = min(limit, MAX_LIMIT)

        users = fetch_photographers(site)
        uploads = fetch_uploads(users, limit)

        sections = [render_user(u, uploads[u]) for u in users if u in uploads]
        rendered = "\n".join(sections)
        body = f"{template_text}\n<!-- Wynik działania Bota -->\n{rendered}"
        return [PageWrite(
            index=1,
            body=body,
            summary=f"[WikiZEIT] Aktualizacja: {self.template_name}",
            scope=self.template_name,
        )], None
