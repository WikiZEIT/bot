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

import smtplib
import traceback
from datetime import datetime
from email.message import EmailMessage


SMTP_HOST = 'localhost'
SMTP_PORT = 25

FROM_ADDR = 'tools.wikizeit-bot@toolforge.org'
TO_ADDR = 'jcubic@jcubic.pl'
SUBJECT_PREFIX = '[WikiZEITBot]'


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

    def page_processed(self):
        self.pages_processed += 1

    def write_succeeded(self):
        self.writes_succeeded += 1

    def record_error(self, where, exc):
        self.errors.append((where, f"{type(exc).__name__}: {exc}"))

    def send_summary(self):
        if not self.enabled:
            return
        elapsed = datetime.now() - self.start
        body = (
            f"Czas trwania: {elapsed}\n"
            f"Stron przetworzonych: {self.pages_processed}\n"
            f"Zapisów udanych: {self.writes_succeeded}\n"
            f"Błędów: {len(self.errors)}\n"
        )
        if self.errors:
            body += "\nSzczegóły błędów:\n"
            for where, exc in self.errors:
                body += f"  - {where}: {exc}\n"
        try:
            _send("Podsumowanie uruchomienia", body)
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
