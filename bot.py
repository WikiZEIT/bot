#!/usr/bin/env python
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

import pywikibot

from handlers import NoOpHandler
from notifications import NotificationManager
from podopieczni import MenteesHandler


DEBUG = False
DEBUG_DIR = 'pages'
EMAIL_NOTIFICATIONS = True

CATEGORY = 'Kategoria:Strony monitorowane przez bota WikiZEIT'

HANDLERS = [
    MenteesHandler(),
    NoOpHandler(),
]
HANDLERS_BY_NAME = {h.template_name.lower(): h for h in HANDLERS}


def build_template_regex(handlers):
    names = '|'.join(re.escape(h.template_name) for h in handlers)
    return re.compile(
        rf"\{{\{{\s*({names})\s*(?:\|([^}}]*))?\s*\}}\}}",
        flags=re.I,
    )


TEMPLATE_RE = build_template_regex(HANDLERS)


def format_index(index, width):
    return f"{index:0{width}d}"


def parse_params(params_str):
    params = {}
    if not params_str:
        return params
    for part in params_str.split('|'):
        if '=' not in part:
            continue
        key, value = part.split('=', 1)
        params[key.strip()] = value.strip()
    return params


def persist_write(parent_page, write, width):
    if write.index == 1:
        page = parent_page
    else:
        title = f"{parent_page.title()}/{format_index(write.index, width)}"
        page = pywikibot.Page(parent_page.site, title)

    if DEBUG:
        debug_dir = os.path.join(DEBUG_DIR, write.scope) if write.scope else DEBUG_DIR
        os.makedirs(debug_dir, exist_ok=True)
        path = os.path.join(debug_dir, format_index(write.index, width))
        with open(path, 'w', encoding='utf-8') as f:
            f.write(write.body)
        pywikibot.output(f"[DEBUG] zapisano {path}")
        return True
    if page.exists() and page.text == write.body:
        return False
    page.text = write.body
    page.save(summary=write.summary, minor=True)
    return True


def main():
    notif = NotificationManager(enabled=EMAIL_NOTIFICATIONS and not DEBUG)
    try:
        site = pywikibot.Site('pl', 'wikipedia')
        cat = pywikibot.Category(site, CATEGORY)

        for page in cat.articles():
            if not page.exists():
                continue

            notif.page_processed()
            pywikibot.output(f"Przetwarzam stronę: {page.title()}")
            try:
                m = TEMPLATE_RE.search(page.text)
                if not m:
                    continue

                template_name = m.group(1)
                params = parse_params(m.group(2))
                handler = HANDLERS_BY_NAME.get(template_name.lower())
                if handler is None:
                    pywikibot.output(f"Nieznany szablon: {template_name!r}")
                    continue

                writes = handler.handle(site, page, params, m.group(0))
                width = len(str(len(writes))) if writes else 1
                for write in writes:
                    try:
                        if persist_write(page, write, width):
                            notif.write_succeeded()
                            pywikibot.output(
                                f"Sukces! {page.title()} szablon={template_name} index={write.index}"
                            )
                    except Exception as exc:
                        notif.record_error(f"{page.title()} index={write.index}", exc)
                        pywikibot.error(
                            f"Błąd przy zapisie {page.title()} index={write.index}: {exc}"
                        )
            except Exception as exc:
                notif.record_error(page.title(), exc)
                pywikibot.error(f"Błąd przy stronie {page.title()}: {exc}")

        notif.send_summary()
    except Exception as exc:
        notif.send_failure(exc)
        raise


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
