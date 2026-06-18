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


SMTP_HOST = 'mail.tools.wmcloud.org'
SMTP_PORT = 25

FROM_ADDR = 'tools.wikizeit-bot@toolforge.org'
TO_ADDR = 'jcubic@jcubic.pl'
SUBJECT_PREFIX = '[WikiZEITBot]'

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

    def _format_digest(self, entries):
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
        if errors:
            body += "\nBłędy:\n"
            for when, where, exc in errors:
                body += f"  - {when} {where}: {exc}\n"
        return body

    def finish(self, send_email=False):
        if not self.enabled:
            return
        self._append_log()
        if not send_email:
            return
        entries = self._read_log()
        body = self._format_digest(entries)
        try:
            _send("Podsumowanie", body)
            self._clear_log()
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
