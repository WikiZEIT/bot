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

import argparse
import dataclasses
import logging
import os
import re
from datetime import datetime

import pywikibot

from fotografia import FotografiaHandler
from handlers import SzablonHandler
from notifications import NotificationManager
from parsing import (
    build_template_start_regex,
    find_template_in_text,
    parse_params,
)
from podopieczni import MenteesHandler


class _SuppressRetryTraceback(logging.Filter):
    """Drop pywikibot's ERROR-level tracebacks for recoverable timeouts.
    Pywikibot retries internally; the traceback in the log is noise."""

    def filter(self, record):
        if record.levelno != logging.ERROR:
            return True
        msg = record.getMessage()
        if 'Read timed out' in msg or 'ServerError' in msg:
            return False
        if record.exc_info:
            _, exc_value, _ = record.exc_info
            if exc_value and 'Read timed out' in str(exc_value):
                return False
        return True


_retry_filter = _SuppressRetryTraceback()
for _name in ('pywikibot', 'pywikibot.comms.http', 'pywikibot.data.api._requests'):
    logging.getLogger(_name).addFilter(_retry_filter)


DEBUG = False
DEBUG_DIR = 'pages'
EMAIL_NOTIFICATIONS = True

CATEGORY = 'Kategoria:Strony monitorowane przez bota WikiZEIT'

HANDLERS = [
    MenteesHandler(),
    FotografiaHandler(),
    SzablonHandler(),
]
HANDLERS_BY_NAME = {h.template_name.lower(): h for h in HANDLERS}


def build_marker_regexes(handlers):
    names = '|'.join(re.escape(h.template_name) for h in handlers)
    # `[\s\S]*?` (non-greedy any-char incl. newlines) lets the params body
    # contain `>` — previously `[^>]*?` choked on etykieta values like
    # `<center>...</center>` and the bot fell into first-run mode every cycle,
    # piling up duplicate marker blocks on every save.
    begin = re.compile(
        rf"<!--\s*WikiZEITBot:({names})(?:\|([\s\S]*?))?\s*-->",
        flags=re.I,
    )
    end = re.compile(
        rf"<!--\s*/WikiZEITBot:({names})\s*-->",
        flags=re.I,
    )
    return begin, end


TEMPLATE_START_RE = build_template_start_regex([h.template_name for h in HANDLERS])
MARKER_BEGIN_RE, MARKER_END_RE = build_marker_regexes(HANDLERS)


def find_template(text, start_pos=0):
    return find_template_in_text(TEMPLATE_START_RE, text, start_pos)


def make_begin_marker(template_name, params):
    # Params are intentionally NOT serialized into the new marker — the
    # template is preserved on the page and is the authoritative source of
    # params. Keeping the marker simple sidesteps quoting headaches with `>`,
    # `-->`, etc. that could appear in values like `etykieta=<center>…`.
    # The reader regex (build_marker_regexes) still tolerates legacy markers
    # that DO carry params, for backwards compatibility.
    return f"<!-- WikiZEITBot:{template_name} -->"


def make_end_marker(template_name):
    return f"<!-- /WikiZEITBot:{template_name} -->"


def build_template_invocation(template_name, params):
    if not params:
        return f"{{{{{template_name}}}}}"
    return f"{{{{{template_name}|" + '|'.join(f"{k}={v}" for k, v in params.items()) + "}}"


def find_injection_site(page_text):
    """Locate where the bot should inject content. Template is the source of
    truth for params; markers delimit the bot-managed block.

    Returns (template_name, params, prefix, suffix). The controller composes
    the new page as `prefix + begin_marker + body + end_marker + suffix`,
    inserting newlines between segments.

    Five cases:
      A. Template + matching begin/end markers — normal subsequent run.
         prefix = text before begin marker (template + anything in between is
         kept); suffix = text after end marker.
      B. Template + begin marker only (no matching end) — legacy state /
         partial write. prefix = text before begin marker; suffix discarded.
      C. Template only, no markers — first run. prefix = text up to and
         including the template; suffix = text after the template (preserved
         verbatim — user content "below" the template is kept).
      D. No template but a begin marker exists — migration: a previous
         version of the bot removed the template. The template is
         reconstructed from the marker's params and re-injected into prefix.
         End-marker rules as in A/B.
      E. Nothing matched — return None.
    """
    template_match = find_template(page_text)
    if template_match is not None:
        template_name, params_text, _, template_end = template_match
        params = parse_params(params_text)

        begin = MARKER_BEGIN_RE.search(page_text, template_end)
        if begin is None:
            # Case C: first run, no markers yet.
            return (template_name, params, page_text[:template_end], page_text[template_end:])

        # Pick the LAST matching end marker after the first begin marker.
        # If past buggy runs stacked duplicate `begin … end | begin … end`
        # blocks, this collapses them into a single replacement region.
        last_end = None
        for m in MARKER_END_RE.finditer(page_text, begin.end()):
            if m.group(1).lower() == begin.group(1).lower():
                last_end = m

        if last_end is not None:
            # Case A: normal subsequent run.
            return (template_name, params, page_text[:begin.start()], page_text[last_end.end():])

        # Case B: begin without any matching end — replace from begin onwards.
        return (template_name, params, page_text[:begin.start()], '')

    # Case D: no template; try to recover from a stray marker.
    begin = MARKER_BEGIN_RE.search(page_text)
    if begin is None:
        return None

    template_name = begin.group(1)
    params = parse_params(begin.group(2) or '')
    restored_template = build_template_invocation(template_name, params)
    prefix = page_text[:begin.start()] + restored_template

    end = MARKER_END_RE.search(page_text, begin.end())
    if end and end.group(1).lower() == begin.group(1).lower():
        suffix = page_text[end.end():]
    else:
        suffix = ''
    return (template_name, params, prefix, suffix)


def format_index(index, width):
    return f"{index:0{width}d}"


def persist_write(parent_page, write, width, total_writes):
    if write.index == 1:
        page = parent_page
    else:
        title = f"{parent_page.title()}/{format_index(write.index, width)}"
        page = pywikibot.Page(parent_page.site, title)

    if DEBUG:
        scope_dir = os.path.join(DEBUG_DIR, write.scope) if write.scope else DEBUG_DIR
        page_title = parent_page.title()
        if total_writes == 1:
            # Single-page output (e.g. Fotografia): file path mirrors the wiki
            # page title; slashes become directories so the URL hierarchy is
            # visible in the filesystem.
            path = os.path.join(scope_dir, page_title)
            os.makedirs(os.path.dirname(path), exist_ok=True)
        else:
            # Multi-page output (Podopieczni): nest main + subpages inside a
            # directory named after the parent title so the main page doesn't
            # clash with the subpage directory.
            page_dir = os.path.join(scope_dir, page_title)
            os.makedirs(page_dir, exist_ok=True)
            if write.index == 1:
                path = os.path.join(page_dir, '_main')
            else:
                path = os.path.join(page_dir, format_index(write.index, width))
        with open(path, 'w', encoding='utf-8') as f:
            f.write(write.body)
        pywikibot.output(f"[DEBUG] zapisano {path}")
        return True
    if page.exists() and page.text == write.body:
        return False
    page.text = write.body
    page.save(summary=write.summary, minor=True)
    return True


def main(new_only=False, send_summary=False, migrate=False):
    start = datetime.now()
    flags = []
    if migrate:
        flags.append('--migrate')
    if new_only:
        flags.append('--new-only')
    if send_summary:
        flags.append('--summary')
    flags_str = ' '.join(flags) if flags else '(brak flag)'
    pywikibot.output(f"==== START {start.isoformat(timespec='seconds')} {flags_str} ====")

    notif = NotificationManager(enabled=EMAIL_NOTIFICATIONS and not DEBUG and not migrate)
    try:
        site = pywikibot.Site('pl', 'wikipedia')
        cat = pywikibot.Category(site, CATEGORY)

        for page in cat.articles():
            if not page.exists():
                continue

            notif.page_processed()
            pywikibot.output(f"Przetwarzam stronę: {page.title()}")
            try:
                site_info = find_injection_site(page.text)
                if site_info is None:
                    continue

                template_name, params, prefix, suffix = site_info
                handler = HANDLERS_BY_NAME.get(template_name.lower())
                if handler is None:
                    pywikibot.output(f"Nieznany szablon: {template_name!r}")
                    continue

                if migrate:
                    handler.migrate(site, page, params)
                    continue

                writes, commit = handler.handle(site, page, params, new_only=new_only)
                if not writes:
                    pywikibot.output(f"Pomijam (bez zmian): {page.title()}")
                    continue

                begin_marker = make_begin_marker(template_name, params)
                end_marker = make_end_marker(template_name)
                width = len(str(len(writes)))
                total_writes = len(writes)
                all_ok = True
                for write in writes:
                    if write.index == 1:
                        prefix_clean = prefix.rstrip('\n')
                        suffix_clean = suffix.lstrip('\n')
                        parts = []
                        if prefix_clean:
                            parts.append(prefix_clean)
                        parts.extend([begin_marker, write.body, end_marker])
                        if suffix_clean:
                            parts.append(suffix_clean)
                        write = dataclasses.replace(write, body='\n'.join(parts))
                    try:
                        if persist_write(page, write, width, total_writes):
                            notif.write_succeeded(page.title())
                            pywikibot.output(
                                f"Sukces! {page.title()} szablon={template_name} index={write.index}"
                            )
                    except Exception as exc:
                        all_ok = False
                        notif.record_error(f"{page.title()} index={write.index}", exc)
                        pywikibot.error(
                            f"Błąd przy zapisie {page.title()} index={write.index}: {exc}"
                        )

                if all_ok and commit is not None and not DEBUG:
                    try:
                        commit()
                    except Exception as exc:
                        pywikibot.error(f"Błąd zapisu stanu dla {page.title()}: {exc}")
            except Exception as exc:
                notif.record_error(page.title(), exc)
                pywikibot.error(f"Błąd przy stronie {page.title()}: {exc}")

        if not migrate:
            notif.finish(send_email=send_summary)
    except Exception as exc:
        notif.send_failure(exc)
        end = datetime.now()
        pywikibot.output(
            f"==== KONIEC {end.isoformat(timespec='seconds')} "
            f"czas={end - start} BŁĄD ===="
        )
        raise

    end = datetime.now()
    pywikibot.output(
        f"==== KONIEC {end.isoformat(timespec='seconds')} czas={end - start} ===="
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="WikiZEIT Bot.")
    parser.add_argument(
        '--new-only',
        action='store_true',
        help="Skip pages whose params and inputs match the last saved state.",
    )
    parser.add_argument(
        '--summary',
        action='store_true',
        help="Send the accumulated digest email at the end of the run and clear the log.",
    )
    parser.add_argument(
        '--migrate',
        action='store_true',
        help="Populate the database from the current wiki state without re-rendering pages.",
    )
    args = parser.parse_args()
    try:
        main(new_only=args.new_only, send_summary=args.summary, migrate=args.migrate)
    except KeyboardInterrupt:
        pass
