# WikiZEIT Bot

A [pywikibot](https://www.mediawiki.org/wiki/Manual:Pywikibot)-based bot for the Polish Wikipedia,
running as [WikiZEITBot](https://pl.wikipedia.org/wiki/Wikipedysta:WikiZEITBot).

The bot scans pages in the category **Kategoria:Strony monitorowane przez bota WikiZEIT**, looks
for a template that declares an action, and writes the rendered result back to the page (using
paginated subpages when the output is large).

## Wiki-side template

```wiki
{{Wikipedysta:WikiZEITBot/szablon|akcja=<name>|<key>=<value>|...}}
```

### Supported actions

- **`akcja=podopieczni|user=<mentor>`** — list mentees of the given mentor. Blocked users and
  members of the `editor`/`sysop` groups are filtered out; the remainder is sorted by editcount
  (descending) and split into subpages of `MENTEES_PER_PAGE` mentees, named `<page>/2`, `/3`, ....

## Local setup

```bash
git clone git@github.com:WikiZEIT/bot.git
cd bot
python3 -m venv venv
source venv/bin/activate
pip install pywikibot
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

Configurable constants at the top of `bot.py`:

| Constant | Meaning |
| --- | --- |
| `DEBUG` | When `True`, the bot writes each page's output to `DEBUG_DIR/<n>` files instead of saving to the wiki. Flip to `False` for production. |
| `DEBUG_DIR` | Output directory for the dry-run (default `pages`). |
| `MENTEES_PER_PAGE` | Pagination size for `podopieczni`. |
| `EXCLUDED_GROUPS` | User groups filtered out of the mentee list (default `{'editor', 'sysop'}`). |

Then:

```bash
python bot.py
```

## Toolforge deployment

Tool: `wikizeit-bot` (tool home at `/data/project/wikizeit-bot/`).

```bash
become wikizeit-bot
git clone git@github.com:WikiZEIT/bot.git
cd bot && python3 -m venv venv && venv/bin/pip install pywikibot

toolforge-jobs run wikizeit-hourly \
  --image python3.11 \
  --schedule '0 * * * *' \
  --command '/data/project/wikizeit-bot/bot/venv/bin/python /data/project/wikizeit-bot/bot/bot.py'
```

Keep `user-config.py` and `user-password.py` in `/data/project/wikizeit-bot/` (outside the repo)
and pass `--env PYWIKIBOT_DIR=/data/project/wikizeit-bot` to the jobs command so pywikibot finds
them.

## License

WikiZEIT Bot — pywikibot-based bot for the Polish Wikipedia.
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
