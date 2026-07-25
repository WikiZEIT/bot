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
import smtplib
import traceback
from datetime import datetime
from email.message import EmailMessage

import pywikibot

import db


SMTP_HOST = 'mail.tools.wmcloud.org'
SMTP_PORT = 25

FROM_ADDR = 'tools.wikizeit-bot@toolforge.org'
TO_ADDR = 'bot@wikizeit.edu.pl'
SUBJECT_PREFIX = '[WikiZEITBot]'

# Value of the `email` template param that opts a mentor into their own
# per-mentor newcomer summary (sent via MediaWiki's emailuser API).
EMAIL_OPTIN_VALUE = 'tak'
MENTOR_SUBJECT = 'WikiZEIT: nowi podopieczni'

# Link to a user's contributions (edit history). Spaces in the username become
# underscores, as MediaWiki page URLs require.
CONTRIBS_URL = 'https://pl.wikipedia.org/wiki/Specjalna:Wkład/{user}'

LOG_DIR = os.path.expanduser('~/state/notifications')
LOG_FILE = os.path.join(LOG_DIR, 'runs.jsonl')


def _send(subject, body):
    msg = EmailMessage()
    msg['From'] = FROM_ADDR
    msg['To'] = TO_ADDR
    msg['Subject'] = f"{SUBJECT_PREFIX} {subject}"
    msg.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.send_message(msg)


def email_optin(params):
    """True if a mentor's stored template params carry the `email=tak` flag.

    The check is case-insensitive and tolerant of surrounding whitespace, so
    `Tak`, `TAK`, ` tak ` all opt in. Any other value — or a missing flag —
    opts out."""
    if not params:
        return False
    return str(params.get('email', '')).strip().lower() == EMAIL_OPTIN_VALUE


def select_mentor_recipients(newcomers, get_params):
    """Pick which mentors should receive their own newcomer summary.

    `newcomers` is `{mentor: [mentee, ...]}` (as returned by
    `db.get_newcomers_since`). `get_params` maps a mentor name to that mentor's
    stored template params (typically `db.get_params`). Returns a list of
    `(mentor, names)` for mentors that both opted in via `email=tak` and have
    at least one newcomer this digest — nobody gets an empty summary."""
    recipients = []
    for mentor, names in newcomers.items():
        if not names:
            continue
        if email_optin(get_params(mentor)):
            recipients.append((mentor, names))
    return recipients


def contribs_url(name):
    """URL of a user's contributions (edit history) on pl.wikipedia."""
    return CONTRIBS_URL.format(user=name.replace(' ', '_'))


def format_mentor_summary(mentor, new_names, since, page_url):
    """Render the plain-text body of a single mentor's newcomer summary — the
    mentees added since the previous digest, same as the operator summary. Each
    newcomer is followed by a link to their contributions (edit history). The
    full roster is deliberately NOT listed: a mentor can have thousands of
    mentees, so the mail links to `page_url` — the actual mentee-list page the
    bot processed (omitted if unknown)."""
    lines = [
        f"Cześć {mentor},",
        "",
        f"Od {since} pojawiło się nowych podopiecznych: {len(new_names)}",
        "",
    ]
    for name in new_names:
        lines.append(name)
        lines.append(f"* {contribs_url(name)}")
        lines.append("")
    if page_url:
        lines += [
            "Pełną listę znajdziesz na swojej stronie podopiecznych:",
            "",
            f"* {page_url}",
            "",
        ]
    lines += [
        "--",
        "Ta wiadomość została wysłana automatycznie przez bota WikiZEIT.",
    ]
    return '\n'.join(lines)


def format_mentor_results(results):
    """Render the operator-facing block that reports how the per-mentor emails
    went. `results` is a list of `{'mentor', 'status', 'detail'}` dicts where
    status is `sent` / `skipped` / `failed`. Returns `""` when nothing was
    attempted, so the digest omits the section entirely."""
    if not results:
        return ""
    sent = [r for r in results if r['status'] == 'sent']
    skipped = [r for r in results if r['status'] == 'skipped']
    failed = [r for r in results if r['status'] == 'failed']

    lines = [
        f"\nPowiadomienia e-mail do mentorów: "
        f"{len(sent)} wysłane, {len(skipped)} pominięte, {len(failed)} błędne"
    ]
    if sent:
        lines.append("  wysłane: " + ', '.join(r['mentor'] for r in sent))
    if skipped:
        lines.append("  pominięte: "
                     + ', '.join(f"{r['mentor']} ({r['detail']})" for r in skipped))
    if failed:
        lines.append("  błędy: "
                     + ', '.join(f"{r['mentor']} ({r['detail']})" for r in failed))
    return '\n'.join(lines) + '\n'


class NotificationManager:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.start = datetime.now()
        self.pages_processed = 0
        self.writes_succeeded = 0
        self.errors = []
        self.updated_pages = []

    def page_processed(self):
        self.pages_processed += 1

    def write_succeeded(self, page_title=None):
        self.writes_succeeded += 1
        if page_title and page_title not in self.updated_pages:
            self.updated_pages.append(page_title)

    def record_error(self, where, exc):
        self.errors.append((datetime.now().isoformat(), where, f"{type(exc).__name__}: {exc}"))

    def _append_log(self):
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            entry = {
                'started': self.start.isoformat(),
                'finished': datetime.now().isoformat(),
                'pages_processed': self.pages_processed,
                'writes_succeeded': self.writes_succeeded,
                'updated_pages': self.updated_pages,
                'errors': self.errors,
            }
            with open(LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        except Exception as e:
            print(f"[notifications] Nie udało się zapisać dziennika: {e}")

    def _read_log(self):
        if not os.path.exists(LOG_FILE):
            return []
        entries = []
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return entries

    def _clear_log(self):
        if os.path.exists(LOG_FILE):
            os.remove(LOG_FILE)

    def _format_digest(self, entries, newcomers, since, newcomers_error=None,
                       mentor_results=None):
        if not entries:
            return "Brak zarejestrowanych uruchomień."

        total_pages = sum(e.get('pages_processed', 0) for e in entries)
        total_writes = sum(e.get('writes_succeeded', 0) for e in entries)

        updated = []
        for e in entries:
            for p in e.get('updated_pages', []):
                if p not in updated:
                    updated.append(p)

        errors = []
        for e in entries:
            for item in e.get('errors', []):
                if len(item) == 3:
                    errors.append(tuple(item))
                else:
                    where, exc = item
                    errors.append((e.get('finished', '?'), where, exc))

        body = (
            f"Zakres: {entries[0].get('started', '?')} → {entries[-1].get('finished', '?')}\n"
            f"Liczba uruchomień: {len(entries)}\n"
            f"Stron przetworzonych: {total_pages}\n"
            f"Zapisów udanych: {total_writes}\n"
            f"Błędów: {len(errors)}\n"
        )
        if updated:
            body += f"\nZaktualizowane strony ({len(updated)}):\n"
            for p in updated:
                body += f"  - {p}\n"

        if newcomers_error is not None:
            body += f"\n(Błąd przy pobieraniu nowych podopiecznych: {newcomers_error})\n"
        elif newcomers:
            total_new = sum(len(v) for v in newcomers.values())
            body += f"\nNowi podopieczni od {since} ({total_new}):\n"
            for mentor, names in newcomers.items():
                body += f"  {mentor} (+{len(names)}): {', '.join(names)}\n"

        body += format_mentor_results(mentor_results)

        if errors:
            body += "\nBłędy:\n"
            for when, where, exc in errors:
                body += f"  - {when} {where}: {exc}\n"
        return body

    def _send_mentor_digests(self, site, newcomers, since):
        """Send each opted-in mentor (via `email=tak`) their own newcomer
        summary through MediaWiki's emailuser API.

        Returns a list of `{'mentor', 'status', 'detail'}` outcomes (status is
        `sent` / `skipped` / `failed`) so the operator digest can report what
        happened. Per-mentor failures are isolated — one unreachable mentor
        never blocks the rest, nor the surrounding digest bookkeeping."""
        results = []
        recipients = select_mentor_recipients(newcomers, db.get_params)
        for mentor, names in recipients:
            try:
                user = pywikibot.User(site, mentor)
                if not user.isEmailable():
                    results.append({'mentor': mentor, 'status': 'skipped',
                                    'detail': 'nie przyjmuje e-maili'})
                    print(f"[notifications] Pominięto {mentor}: nie przyjmuje e-maili")
                    continue
                body = format_mentor_summary(mentor, names, since, db.get_page_url(mentor))
                if user.send_email(MENTOR_SUBJECT, body):
                    results.append({'mentor': mentor, 'status': 'sent',
                                    'detail': f'{len(names)} nowych'})
                    print(f"[notifications] Wysłano podsumowanie do {mentor} "
                          f"({len(names)} nowych)")
                else:
                    results.append({'mentor': mentor, 'status': 'failed',
                                    'detail': 'send_email zwróciło False'})
                    print(f"[notifications] send_email zwróciło False dla {mentor}")
            except Exception as e:
                results.append({'mentor': mentor, 'status': 'failed',
                                'detail': f'{type(e).__name__}: {e}'})
                print(f"[notifications] Nie udało się wysłać e-maila do {mentor}: {e}")
        return results

    def finish(self, send_email=False, site=None):
        if not self.enabled:
            return
        self._append_log()
        if not send_email:
            return
        entries = self._read_log()
        since = db.get_last_digest_time() or (entries[0].get('started', '') if entries else '')
        newcomers, newcomers_error = {}, None
        if since:
            try:
                newcomers = db.get_newcomers_since(since)
            except Exception as e:
                newcomers_error = e
        # Send the per-mentor emails first so their outcomes can be folded into
        # the operator digest below.
        mentor_results = []
        if site is not None and newcomers_error is None and newcomers:
            mentor_results = self._send_mentor_digests(site, newcomers, since)
        body = self._format_digest(entries, newcomers, since, newcomers_error, mentor_results)
        try:
            _send("Podsumowanie", body)
            self._clear_log()
            try:
                db.set_last_digest_time()
            except Exception as e:
                print(f"[notifications] Nie udało się zapisać czasu digestu: {e}")
        except Exception as e:
            print(f"[notifications] Nie udało się wysłać podsumowania: {e}")

    def send_failure(self, exc):
        if not self.enabled:
            return
        body = (
            "Bot przerwany przez nieobsłużony wyjątek.\n\n"
            f"Stron przetworzonych przed awarią: {self.pages_processed}\n"
            f"Zapisów udanych przed awarią: {self.writes_succeeded}\n\n"
            "Traceback:\n"
            f"{traceback.format_exc()}"
        )
        try:
            _send("BŁĄD KRYTYCZNY", body)
        except Exception as e:
            print(f"[notifications] Nie udało się wysłać alertu: {e}")
