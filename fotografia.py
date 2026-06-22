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

import json
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

DEFAULT_ETYKIETA = '<center>[[:commons:File:{{plik}}|{{plik}}]]</center>'
LANG = 'pl'

TRANSLATIONS_PATH = os.path.join(os.path.dirname(__file__), 'translations.json')
ETYKIETA_TOKEN_RE = re.compile(r'\{\{([^\s|{}]+)\}\}')

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


def fetch_uploads(users, limit, name_regex=None, mime_filter=None):
    """Return {user: (file_rows, latest_timestamp)} of the `limit` most recent
    uploads per user from the Wikimedia Commons SQL replica. Each `file_row`
    is a dict with the SQL columns we expose to `etykieta`. Users with no
    uploads or no Commons account simply don't appear in the result.

    `name_regex` adds `img_name REGEXP <re>` (case-insensitive via the `(?i)`
    PCRE prefix). `mime_filter` is either `major/minor` (e.g. `image/jpeg`,
    constrains both `img_major_mime` and `img_minor_mime`) or just `major`
    (e.g. `image`, constrains only major)."""
    if not users:
        return {}

    conditions = ["actor.actor_name = %s"]
    if name_regex:
        conditions.append("img_name REGEXP %s")
    if mime_filter:
        if '/' in mime_filter:
            conditions.append("img_major_mime = %s AND img_minor_mime = %s")
        else:
            conditions.append("img_major_mime = %s")
    where = " AND ".join(conditions)

    query = f"""
        SELECT img_name, img_size, img_width, img_height, img_timestamp,
               img_sha1, img_major_mime, img_minor_mime
        FROM image
        JOIN actor ON actor.actor_id = image.img_actor
        WHERE {where}
        ORDER BY img_timestamp DESC
        LIMIT %s
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
            for user in users:
                sql_params = [_canonical_username(user).encode('utf-8')]
                if name_regex:
                    sql_params.append(f"(?i){name_regex}".encode('utf-8'))
                if mime_filter:
                    if '/' in mime_filter:
                        major, minor = mime_filter.split('/', 1)
                        sql_params.append(major.strip().encode('utf-8'))
                        sql_params.append(minor.strip().encode('utf-8'))
                    else:
                        sql_params.append(mime_filter.strip().encode('utf-8'))
                sql_params.append(limit)

                cursor.execute(query, sql_params)
                rows = cursor.fetchall()
                if not rows:
                    continue
                file_rows = [_decode_row(r, user) for r in rows]
                latest = file_rows[0]['img_timestamp']
                result[user] = (file_rows, latest)
    finally:
        conn.close()
    return result


def _decode_row(row, user):
    """Convert pymysql's raw bytes/ints into a clean dict for substitution."""
    def s(v):
        return v.decode('utf-8') if isinstance(v, (bytes, bytearray)) else v
    return {
        'img_name': s(row['img_name']).replace('_', ' '),
        'img_size': row['img_size'],
        'img_width': row['img_width'],
        'img_height': row['img_height'],
        'img_timestamp': s(row['img_timestamp']),
        'img_sha1': s(row['img_sha1']),
        'img_major_mime': s(row['img_major_mime']),
        'img_minor_mime': s(row['img_minor_mime']),
        'actor_name': user,
    }


def load_translations():
    with open(TRANSLATIONS_PATH, 'r', encoding='utf-8') as f:
        return json.load(f).get(LANG, {})


_VAR_MAP = None


def var_map():
    """Lazy-load and cache the user-facing-token → canonical-name map for LANG."""
    global _VAR_MAP
    if _VAR_MAP is None:
        _VAR_MAP = load_translations()
    return _VAR_MAP


def format_value(canonical, row):
    """Format a single value for substitution. Honors a `:format` suffix on
    the canonical name — e.g. `img_timestamp:date` returns `YYYY-MM-DD`."""
    if ':' in canonical:
        column, fmt = canonical.split(':', 1)
    else:
        column, fmt = canonical, None

    if column == 'img_mime':
        major = row.get('img_major_mime') or ''
        minor = row.get('img_minor_mime') or ''
        return f"{major}/{minor}" if major or minor else ''

    if column == 'img_timestamp':
        ts = row.get('img_timestamp') or ''
        if fmt == 'date' and len(ts) >= 8:
            return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
        if fmt == 'iso' and len(ts) >= 14:
            return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}T{ts[8:10]}:{ts[10:12]}:{ts[12:14]}Z"
        return ts

    val = row.get(column)
    return str(val) if val is not None else ''


def substitute_etykieta(etykieta, row):
    """Replace `{{token}}` markers in `etykieta` with values from `row`.
    Unknown tokens are left untouched, so literal templates like `{{own}}`
    survive intact when there's no `own` variable."""
    mapping = var_map()

    def replace(m):
        token = m.group(1).strip()
        canonical = mapping.get(token)
        if canonical is None:
            return m.group(0)
        return format_value(canonical, row)

    return ETYKIETA_TOKEN_RE.sub(replace, etykieta)


def render_user_header(user):
    """Standard plainlinks-styled H3 header for a user."""
    user_url = user.replace(' ', '_')
    return (
        f'=== <span class="plainlinks">'
        f'[https://pl.wikipedia.org/wiki/User:{user_url} {user}]'
        f'</span> ==='
    )


def render_gallery(file_rows, etykieta):
    """Wiki gallery for the given files, or a no-uploads comment if empty."""
    if not file_rows:
        return '<!-- brak zdjęć -->'
    lines = "\n".join(
        f"File:{row['img_name']}|{substitute_etykieta(etykieta, row)}"
        for row in file_rows
    )
    return f"<gallery>\n{lines}\n</gallery>"


def render_user_section(user, file_rows, etykieta):
    """Per-user H3 header followed by gallery / empty-comment."""
    return f"{render_user_header(user)}\n{render_gallery(file_rows, etykieta)}"


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
        name_regex = params.get('nazwa pliku', '').strip() or None
        mime_filter = params.get('mime', '').strip() or None
        etykieta = params.get('etykieta', '').strip() or DEFAULT_ETYKIETA

        uploads = fetch_uploads(users, limit, name_regex=name_regex, mime_filter=mime_filter)

        if mode == 'page':
            if self._should_split(params):
                cutoff = (datetime.now(timezone.utc)
                          - timedelta(days=self._threshold_days(params))).strftime('%Y%m%d%H%M%S')

                active = []
                inactive = []
                for user in users:
                    file_rows, latest = uploads.get(user, ([], None))
                    if latest and latest >= cutoff:
                        active.append((user, file_rows))
                    else:
                        inactive.append((user, file_rows))

                active.sort(key=lambda x: x[0].casefold())
                inactive.sort(key=lambda x: x[0].casefold())

                sections = []
                if active:
                    sections.append("== Aktywni ==\n" + "\n".join(
                        render_user_section(u, rows, etykieta) for u, rows in active
                    ))
                if inactive:
                    sections.append("== Nieaktywni ==\n" + "\n".join(
                        render_user_section(u, rows, etykieta) for u, rows in inactive
                    ))
                rendered = "\n".join(sections)
            else:
                entries = [(u, uploads.get(u, ([], None))[0]) for u in users]
                entries.sort(key=lambda x: x[0].casefold())
                rendered = "\n".join(
                    render_user_section(u, rows, etykieta) for u, rows in entries
                )

        elif mode == 'multi':
            rendered = "\n".join(
                render_user_section(u, uploads.get(u, ([], None))[0], etykieta)
                for u in users
            )

        else:  # single
            user = users[0]
            file_rows = uploads.get(user, ([], None))[0]
            header = params.get('nagłówek', '').strip()
            if header:
                rendered = f"=== {header} ===\n{render_gallery(file_rows, etykieta)}"
            else:
                rendered = render_gallery(file_rows, etykieta)

        return [PageWrite(
            index=1,
            body=rendered,
            summary=f"[WikiZEIT] Aktualizacja: {self.template_name}",
            scope=self.template_name,
        )], None
