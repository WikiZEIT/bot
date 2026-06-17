# WikiZEIT Bot

A [pywikibot](https://www.mediawiki.org/wiki/Manual:Pywikibot)-based bot for the Polish Wikipedia,
running as [WikiZEITBot](https://pl.wikipedia.org/wiki/Wikipedysta:WikiZEITBot).

The bot scans pages in the category **Kategoria:Strony monitorowane przez bota WikiZEIT**, looks
for a known template invocation on each page, dispatches by template name to the matching handler
class, and writes the rendered result back to the page (using paginated subpages when the output
is large).

## Supported wiki-side templates

- **`{{Podopieczni|przewodnik=<mentor>|limit=<n>}}`** — list mentees of the given mentor.
  `przewodnik` is the mentor username (required); `limit` is an optional hard cap on the rendered
  mentee count. Blocked users and members of the `editor`/`sysop` groups are filtered out. When
  `USE_SQL` is on, only mentees who edited within `LAST_EDIT_CUTOFF_DAYS` survive, sorted by
  last-edit timestamp (descending); otherwise the remainder is sorted by editcount. The list is
  split into subpages of `MenteesHandler.items_per_page` mentees each, named `<page>/00002`,
  `/00003`, ….
- **`{{Wikipedysta:WikiZEITBot/szablon}}`** — no-op test slot. The bot recognizes it and does
  nothing. Reserved for new handlers under development.

## Architecture

- `bot.py` — controller. Scans the category, matches the regex generated from registered
  handlers, parses params, calls `handler.handle(...)`, and persists each returned `PageWrite`.
- `handlers.py` — `TemplateHandler`, `PaginatedHandler` (chunking + main/sub envelopes),
  `NoOpHandler`, and the `PageWrite` dataclass.
- `podopieczni.py` — `MenteesHandler` and all mentee-specific code (mentee fetch, user-info via
  API or SQL, eligibility filter, render template).

Adding a new template:

1. Subclass `TemplateHandler` (one-shot output) or `PaginatedHandler` (paginated output).
2. Set `template_name` to the exact wiki template name.
3. Implement `handle()`, or for paginated handlers `fetch_items()` + `render_item()`.
4. Register an instance in `HANDLERS` inside `bot.py`.

## Local setup

```bash
git clone git@github.com:WikiZEIT/bot.git
cd bot
python3 -m venv venv
source venv/bin/activate
pip install pywikibot pymysql
```

Create `user-config.py` next to `bot.py`:

```python
family = 'wikipedia'
mylang = 'pl'
usernames['wikipedia']['pl'] = 'WikiZEITBot'
password_file = 'user-password.py'
```

Create `user-password.py` from a [BotPassword](https://www.mediawiki.org/wiki/Manual:Bot_passwords)
issued at `Specjalna:HasłaBotów`. The first `BotPassword` argument is the **suffix only**, not the
full `user@suffix` login:

```python
('WikiZEITBot', BotPassword('<suffix>', '<generated-token>'))
```

The BotPassword must grant *Edit existing pages*, *Create, edit, and move pages*, and *High-volume
editing* (without the last grant pywikibot logs a `'bot' right wasn't activated` warning and edits
don't get the bot flag).

## Running

Configurable constants:

`bot.py` (controller):

| Constant | Meaning |
| --- | --- |
| `DEBUG` | When `True`, the bot writes each page's output to `DEBUG_DIR/<n>` files instead of saving to the wiki. Flip to `False` for production. |
| `DEBUG_DIR` | Output directory for the dry-run (default `pages`). |
| `CATEGORY` | Name of the monitoring category the bot scans. |

`podopieczni.py` (mentees handler):

| Constant | Meaning |
| --- | --- |
| `USE_SQL` | When `True`, fetch user info from the Wikimedia SQL replica (`replica.my.cnf`) and sort mentees by last-edit timestamp. Only works on Toolforge. Leave `False` for local testing. |
| `LAST_EDIT_CUTOFF_DAYS` | In SQL mode, drop mentees whose last edit is older than this many days. |
| `EXCLUDED_GROUPS` | User groups filtered out of the mentee list (default `{'editor', 'sysop'}`). |
| `MenteesHandler.items_per_page` | Pagination size. |
| `MenteesHandler.subpage_prefix` | Wikitext prepended to each subpage body. |

Then:

```bash
python bot.py
```

## Toolforge deployment

Tool: `wikizeit-bot` (tool home at `/data/project/wikizeit-bot/`).

```bash
become wikizeit-bot
git clone git@github.com:WikiZEIT/bot.git
cd bot && python3 -m venv venv && venv/bin/pip install pywikibot pymysql

toolforge-jobs run wikizeit-hourly \
  --image python3.11 \
  --schedule '0 * * * *' \
  --command '/data/project/wikizeit-bot/bot/venv/bin/python /data/project/wikizeit-bot/bot/bot.py'
```

Keep `user-config.py` and `user-password.py` in `/data/project/wikizeit-bot/` (outside the repo)
and pass `--env PYWIKIBOT_DIR=/data/project/wikizeit-bot` to the jobs command so pywikibot finds
them.

## License

Copyright (C) 2026 [Jakub T. Jankiewicz](https://jakub.jankiewicz.org/)

This program is free software: you can redistribute it and/or modify it under the terms of the GNU
Affero General Public License as published by the Free Software Foundation, either version 3 of
the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without
even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License along with this program.
If not, see <https://www.gnu.org/licenses/> or
[LICENSE](https://github.com/WikiZEIT/bot/blob/master/LICENSE) in this repository.
