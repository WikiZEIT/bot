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
import unicodedata
from datetime import datetime, timedelta, timezone

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
DEFAULT_THRESHOLD_DAYS = 90

# Matches the first user link in a table row, e.g. `[[user:CLI|CLI]]` or
# `[[Wikipedysta:Czupirek|czupirek]]`. Commons cross-wiki links like
# `[[:w:commons:User:CLI/Gallery|...]]` don't match because they start with
# `[[:` not `[[user`/`[[Wikipedysta`.
USER_LINK_RE = re.compile(r'\[\[(?:user|Wikipedysta):([^|\]]+)', flags=re.I)
ROW_SEP_RE = re.compile(r'\n\|-')

USER_TEMPLATE = """=== <span class="plainlinks">[https://pl.wikipedia.org/wiki/User:<user_url> <user>]</span> ===
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


def _canonical_username(name):
    """Apply MediaWiki's first-letter uppercase rule and NFC normalize."""
    if not name:
        return name
    name = unicodedata.normalize('NFC', name)
    return name[0].upper() + name[1:]


def fetch_uploads(users, limit):
    """Return {user: (files, latest_timestamp)} of the `limit` most recent
    uploads per user from the Wikimedia Commons SQL replica. Users with no
    uploads or no Commons account simply don't appear in the result. The
    `latest_timestamp` is a 14-char MediaWiki UTC timestamp string of the
    most-recent upload."""
    if not users:
        return {}

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
            for user in users:
                db_name = _canonical_username(user).encode('utf-8')
                cursor.execute(
                    """
                    SELECT img_name, img_timestamp
                    FROM image
                    JOIN actor ON actor.actor_id = image.img_actor
                    WHERE actor.actor_name = %s
                    ORDER BY img_timestamp DESC
                    LIMIT %s
                    """,
                    (db_name, limit),
                )
                rows = cursor.fetchall()
                if not rows:
                    continue
                files = [
                    row['img_name'].decode('utf-8').replace('_', ' ')
                    for row in rows
                ]
                latest = rows[0]['img_timestamp']
                if isinstance(latest, bytes):
                    latest = latest.decode('utf-8')
                result[user] = (files, latest)
    finally:
        conn.close()
    return result


def render_user(user, files):
    files_text = "\n".join(
        f"File:{f}|<center>[[:commons:File:{f}|{f}]]</center>"
        for f in files
    )
    return (USER_TEMPLATE
            .replace('<user_url>', user.replace(' ', '_'))
            .replace('<user>', user)
            .replace('<files>', files_text))


class FotografiaHandler(TemplateHandler):
    template_name = "Fotografia"

    def handle(self, site, page, params, new_only=False):
        raw = params.get('limit')
        try:
            limit = int(raw)
            if limit <= 0:
                limit = DEFAULT_LIMIT
        except (TypeError, ValueError):
            limit = DEFAULT_LIMIT
        limit = min(limit, MAX_LIMIT)

        raw_threshold = params.get('próg dni')
        try:
            threshold_days = int(raw_threshold)
            if threshold_days <= 0:
                threshold_days = DEFAULT_THRESHOLD_DAYS
        except (TypeError, ValueError):
            threshold_days = DEFAULT_THRESHOLD_DAYS

        cutoff = (datetime.now(timezone.utc)
                  - timedelta(days=threshold_days)).strftime('%Y%m%d%H%M%S')

        users = fetch_photographers(site)
        uploads = fetch_uploads(users, limit)

        active = []
        inactive = []
        for user in users:
            if user not in uploads:
                continue
            files, latest = uploads[user]
            entry = (latest, user, files)
            if latest >= cutoff:
                active.append(entry)
            else:
                inactive.append(entry)

        active.sort(reverse=True)
        inactive.sort(reverse=True)

        sections = []
        if active:
            sections.append("== Aktywni ==\n" + "\n".join(
                render_user(u, f) for _, u, f in active
            ))
        if inactive:
            sections.append("== Nieaktywni ==\n" + "\n".join(
                render_user(u, f) for _, u, f in inactive
            ))
        rendered = "\n".join(sections)

        return [PageWrite(
            index=1,
            body=rendered,
            summary=f"[WikiZEIT] Aktualizacja: {self.template_name}",
            scope=self.template_name,
        )], None
