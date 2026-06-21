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


DEFAULT_SOURCE_PAGE = 'Wikiprojekt:Fotografia/Uczestnicy'

COMMONS_HOST = 'commonswiki.analytics.db.svc.wikimedia.cloud'
COMMONS_DB = 'commonswiki_p'
REPLICA_CNF = os.path.expanduser('~/replica.my.cnf')

DEFAULT_LIMIT = 10
MAX_LIMIT = 100
DEFAULT_THRESHOLD_DAYS = 90

# Matches a User: / Wikipedysta: link anywhere in wikitext. Skips a leading
# `:` (interwiki-style `[[:user:X]]`). Stops at `|`, `]`, or `/` so subpages
# like `[[Wikipedysta:Foo/Brudnopis]]` reduce to the bare username `Foo`.
USER_LINK_RE = re.compile(r'\[\[:?(?:user|Wikipedysta):([^|\]/]+)', flags=re.I)


def fetch_users_from_page(page):
    """Extract all distinct User:/Wikipedysta: links from the page, preserving
    first-occurrence order."""
    text = page.text
    users = []
    seen = set()
    for m in USER_LINK_RE.finditer(text):
        name = m.group(1).strip().replace('_', ' ')
        if not name or name in seen:
            continue
        seen.add(name)
        users.append(name)
    return users


def resolve_users(site, params):
    """Return (mode, payload) based on `fotograf` and `źródło` params.

    `fotograf` (one or more usernames) takes precedence over `źródło` (a wiki
    page to scrape) when both are set. When neither is set, defaults to
    scraping DEFAULT_SOURCE_PAGE.

    Modes:
      ('multi', [users])   — `fotograf` had multiple comma-separated names.
      ('single', [user])   — `fotograf` had a single name.
      ('page', [users])    — `źródło` (or default) scraped for user links.
      ('error', name)      — `źródło` was set but the page doesn't exist;
                             `name` is the requested page title.
    """
    fotograf = params.get('fotograf', '').strip()
    if fotograf:
        if ',' in fotograf:
            seen = set()
            names = []
            for part in fotograf.split(','):
                n = part.strip()
                if n and n not in seen:
                    seen.add(n)
                    names.append(n)
            return 'multi', names
        return 'single', [fotograf]

    source = params.get('źródło', '').strip() or DEFAULT_SOURCE_PAGE
    src_page = pywikibot.Page(site, source)
    if not src_page.exists():
        return 'error', source
    return 'page', fetch_users_from_page(src_page)


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


def render_user_header(user):
    """Standard plainlinks-styled H3 header for a user."""
    user_url = user.replace(' ', '_')
    return (
        f'=== <span class="plainlinks">'
        f'[https://pl.wikipedia.org/wiki/User:{user_url} {user}]'
        f'</span> ==='
    )


def render_gallery(files):
    """Wiki gallery for the given files, or a no-uploads comment if empty."""
    if not files:
        return '<!-- brak zdjęć -->'
    lines = "\n".join(
        f"File:{f}|<center>[[:commons:File:{f}|{f}]]</center>"
        for f in files
    )
    return f"<gallery>\n{lines}\n</gallery>"


def render_user_section(user, files):
    """Per-user H3 header followed by gallery / empty-comment."""
    return f"{render_user_header(user)}\n{render_gallery(files)}"


class FotografiaHandler(TemplateHandler):
    template_name = "Fotografia"

    def _resolve_limit(self, params):
        """Per-user upload cap. Numeric values are capped at MAX_LIMIT;
        anything else falls back to DEFAULT_LIMIT. Applies in every mode."""
        raw = params.get('limit', '').strip()
        try:
            n = int(raw)
            if n <= 0:
                return DEFAULT_LIMIT
            return min(n, MAX_LIMIT)
        except (TypeError, ValueError):
            return DEFAULT_LIMIT

    def _should_split(self, params):
        """Active/inactive split (page mode only) is on by default;
        `próg dni=nie` turns it off and produces a single flat list."""
        return params.get('próg dni', '').strip().lower() != 'nie'

    def _threshold_days(self, params):
        raw = params.get('próg dni')
        try:
            d = int(raw)
            if d <= 0:
                d = DEFAULT_THRESHOLD_DAYS
        except (TypeError, ValueError):
            d = DEFAULT_THRESHOLD_DAYS
        return d

    def handle(self, site, page, params, new_only=False):
        mode, payload = resolve_users(site, params)

        if mode == 'error':
            return [PageWrite(
                index=1,
                body=f"<!-- nie znaleziono strony źródłowej: {payload} -->",
                summary=f"[WikiZEIT] {self.template_name}: brak strony źródłowej",
                scope=self.template_name,
            )], None

        users = payload
        limit = self._resolve_limit(params)
        uploads = fetch_uploads(users, limit)

        if mode == 'page':
            if self._should_split(params):
                cutoff = (datetime.now(timezone.utc)
                          - timedelta(days=self._threshold_days(params))).strftime('%Y%m%d%H%M%S')

                active = []
                inactive = []
                for user in users:
                    files, latest = uploads.get(user, ([], None))
                    if latest and latest >= cutoff:
                        active.append((user, files))
                    else:
                        inactive.append((user, files))

                active.sort(key=lambda x: x[0].casefold())
                inactive.sort(key=lambda x: x[0].casefold())

                sections = []
                if active:
                    sections.append("== Aktywni ==\n" + "\n".join(
                        render_user_section(u, f) for u, f in active
                    ))
                if inactive:
                    sections.append("== Nieaktywni ==\n" + "\n".join(
                        render_user_section(u, f) for u, f in inactive
                    ))
                rendered = "\n".join(sections)
            else:
                entries = [(u, uploads.get(u, ([], None))[0]) for u in users]
                entries.sort(key=lambda x: x[0].casefold())
                rendered = "\n".join(
                    render_user_section(u, f) for u, f in entries
                )

        elif mode == 'multi':
            rendered = "\n".join(
                render_user_section(u, uploads.get(u, ([], None))[0])
                for u in users
            )

        else:  # single
            user = users[0]
            files = uploads.get(user, ([], None))[0]
            header = params.get('nagłówek', '').strip()
            if header:
                rendered = f"=== {header} ===\n{render_gallery(files)}"
            else:
                rendered = render_gallery(files)

        return [PageWrite(
            index=1,
            body=rendered,
            summary=f"[WikiZEIT] Aktualizacja: {self.template_name}",
            scope=self.template_name,
        )], None
