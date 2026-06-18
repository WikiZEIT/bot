# WikiZEIT Bot

A [pywikibot](https://www.mediawiki.org/wiki/Manual:Pywikibot)-based bot for the Polish Wikipedia,
running as [WikiZEITBot](https://pl.wikipedia.org/wiki/Wikipedysta:WikiZEITBot).

The bot scans pages in the category **Kategoria:Strony monitorowane przez bota WikiZEIT**, looks
for a known template invocation on each page, dispatches by template name to the matching handler
class, and writes the rendered result back to the page (using paginated subpages when the output
is large).

## Supported wiki-side templates

- **`{{Podopieczni|przewodnik=<mentor>|limit=<n>|edycje=<k>}}`** — list mentees of the given
  mentor. `przewodnik` is the mentor username (required); `limit` overrides the pagination size
  (mentees per page, defaults to `MenteesHandler.items_per_page = 200`); `edycje` controls the
  `limit=` passed to the per-mentee
  `{{Specjalna:Wkład/...}}` transclusion (defaults to `5`). Blocked users and members of the
  `editor`/`sysop` groups are filtered out. When `USE_SQL` is on, only mentees who edited within
  `LAST_EDIT_CUTOFF_DAYS` survive, sorted by last-edit timestamp (descending); otherwise the
  remainder is sorted by editcount. The list is split into subpages of
  `MenteesHandler.items_per_page` mentees each, named `<page>/2`, `/3`, … (padded to the width of
  the largest index).
- **`{{Fotografia}}`** (optional `|limit=<n>`) — gallery of the latest Commons uploads for every
  Wikipedia photographer listed at `Wikiprojekt:Fotografia/Uczestnicy`. `limit` is the per-user
  upload count (default `10`, capped at `20`). Files are fetched from the Wikimedia Commons SQL
  replica, so this template only works on Toolforge.
- **`{{Wikipedysta:WikiZEITBot/szablon}}`** — no-op test slot. The bot recognizes it and does
  nothing. Reserved for new handlers under development.

## Architecture

- `bot.py` — controller. Scans the category, matches the regex generated from registered
  handlers, parses params, calls `handler.handle(...)`, and persists each returned `PageWrite`.
- `handlers.py` — `TemplateHandler`, `PaginatedHandler` (chunking + main/sub envelopes),
  `NoOpHandler`, and the `PageWrite` dataclass.
- `podopieczni.py` — `MenteesHandler` and all mentee-specific code (mentee fetch, user-info via
  API or SQL, eligibility filter, render template).
- `notifications.py` — `NotificationManager`: tracks per-run counters, appends each run to
  `~/state/notifications/runs.jsonl`, and when invoked with `--summary` reads the accumulated
  log, mails a digest, and clears the file. Error emails (`send_failure`) are always sent
  regardless of `--summary`. Only works on Toolforge (relies on the local Exim relay at
  `localhost:25`).
- `db.py` — SQLite store at `~/state/bot.db` (auto-created on first run). Tables:
  `mentor_params` (last seen template params per mentor), `mentee_membership` (per-mentor
  mentee roster with `first_seen` / `last_seen`), `digest_meta` (last sent digest timestamp).
  `update_mentor(...)` atomically reconciles the roster and returns the `(added, removed)` sets.
- `state.py` — legacy generic JSON store; currently unused, kept for reference.

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
pip install -r requirements.txt
```

To upgrade later: `pip install -r requirements.txt --upgrade`.

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
| `EMAIL_NOTIFICATIONS` | When `True` (and `DEBUG` is `False`), send a per-run summary email after a successful run and an urgent email with traceback on crash. Forced off while `DEBUG=True`. |
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
python bot.py              # full update: re-render every monitored page, no email
python bot.py --new-only   # incremental: skip pages whose params + mentee list
                           # match the state stored in ~/state/bot.db
python bot.py --summary    # full update + email the accumulated digest, then clear the log
python bot.py --migrate    # populate ~/state/bot.db from the current wiki state
                           # without re-rendering anything (one-off bootstrap)
```

After deploying or upgrading the bot for the first time on a host where pages were rendered by a
previous version, run `python bot.py --migrate` once. It walks the monitored category, fetches
each mentor's current eligible mentee set, and inserts the rows into `mentee_membership` with a
sentinel `first_seen = 1970-01-01` so they don't appear as newcomers in the next digest. The
following `--new-only` run will then be a cache hit and skip every page that genuinely hasn't
changed.

`--new-only` and `--summary` compose freely — typical Toolforge layout uses `--new-only` hourly
(append-only logging, no mail) and `--summary` daily (full run, send digest).

The `MenteesHandler` reconciles its mentee roster against `~/state/bot.db` after every successful
run. A subsequent `--new-only` run is a cache hit when the stored params match the current ones
**and** the stored mentee set matches the current eligible set **and** the corresponding wiki
pages exist; otherwise it re-renders and updates the DB. Each commit logs `Zmiany u <mentor>:
+N nowych, -M odeszło` so you can see joins and departures in the job log.

The daily digest reads `mentee_membership.first_seen >= digest_meta.last_digest_time` and
appends a "Nowi podopieczni" section listing newcomers per mentor since the previous digest.

The `MenteesHandler` writes `~/state/podopieczni/<mentor>.json` after every successful run
containing the current template params and a SHA-256 hash of the sorted eligible-mentee names.
A subsequent `--new-only` run reads that file; if both `params` and `mentees_hash` match the
current run, the handler returns `[]` and the page is skipped entirely (no wiki traffic).

## Toolforge deployment

Tool: `wikizeit-bot` (tool home at `/data/project/wikizeit-bot/`).

```bash
become wikizeit-bot
git clone git@github.com:WikiZEIT/bot.git
cd bot && python3 -m venv venv && venv/bin/pip install -r requirements.txt pymysql

toolforge-jobs run wikizeit-hourly \
  --image python3.11 \
  --schedule '0 * * * *' \
  --command '/data/project/wikizeit-bot/bot/venv/bin/python /data/project/wikizeit-bot/bot/bot.py --new-only'

toolforge-jobs run wikizeit-daily \
  --image python3.11 \
  --schedule '0 0 * * *' \
  --command '/data/project/wikizeit-bot/bot/venv/bin/python /data/project/wikizeit-bot/bot/bot.py --summary'
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
