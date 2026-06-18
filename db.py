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
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone


DB_DIR = os.path.expanduser('~/state')
DB_PATH = os.path.join(DB_DIR, 'bot.db')


SCHEMA = """
CREATE TABLE IF NOT EXISTS mentor_params (
    mentor TEXT PRIMARY KEY,
    params_json TEXT,
    updated TEXT
);

CREATE TABLE IF NOT EXISTS mentee_membership (
    mentor TEXT,
    mentee TEXT,
    first_seen TEXT,
    last_seen TEXT,
    PRIMARY KEY (mentor, mentee)
);

CREATE INDEX IF NOT EXISTS idx_membership_first_seen
    ON mentee_membership(mentor, first_seen);

CREATE TABLE IF NOT EXISTS digest_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


@contextmanager
def connect():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_params(mentor):
    with connect() as conn:
        row = conn.execute(
            "SELECT params_json FROM mentor_params WHERE mentor = ?",
            (mentor,),
        ).fetchone()
        if not row:
            return None
        return json.loads(row['params_json'])


def get_mentee_set(mentor):
    with connect() as conn:
        rows = conn.execute(
            "SELECT mentee FROM mentee_membership WHERE mentor = ?",
            (mentor,),
        )
        return {row['mentee'] for row in rows}


def update_mentor(mentor, params, current_mentees, first_seen_override=None):
    """Update the mentor's params and reconcile mentee_membership rows.

    Returns (added, removed) sets — names new to this run and names no longer
    eligible. Inserts/updates happen atomically inside a single transaction.

    `first_seen_override` lets the migration backfill rows with a sentinel
    timestamp (e.g. epoch) so they don't appear as newcomers in the next digest.
    """
    now = _now()
    first_seen = first_seen_override or now
    current = set(current_mentees)

    with connect() as conn:
        previous = {row['mentee'] for row in conn.execute(
            "SELECT mentee FROM mentee_membership WHERE mentor = ?",
            (mentor,),
        )}
        added = current - previous
        removed = previous - current

        if added:
            conn.executemany(
                "INSERT INTO mentee_membership (mentor, mentee, first_seen, last_seen) "
                "VALUES (?, ?, ?, ?)",
                [(mentor, m, first_seen, now) for m in added],
            )

        if current:
            placeholders = ','.join(['?'] * len(current))
            conn.execute(
                f"UPDATE mentee_membership SET last_seen = ? "
                f"WHERE mentor = ? AND mentee IN ({placeholders})",
                (now, mentor, *current),
            )

        if removed:
            conn.executemany(
                "DELETE FROM mentee_membership WHERE mentor = ? AND mentee = ?",
                [(mentor, m) for m in removed],
            )

        conn.execute(
            "INSERT OR REPLACE INTO mentor_params (mentor, params_json, updated) "
            "VALUES (?, ?, ?)",
            (mentor, json.dumps(params, sort_keys=True), now),
        )

    return added, removed


def get_newcomers_since(timestamp):
    """Return {mentor: [mentee, ...]} of rows whose first_seen >= timestamp."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT mentor, mentee, first_seen FROM mentee_membership "
            "WHERE first_seen >= ? ORDER BY mentor, mentee",
            (timestamp,),
        )
        result = {}
        for row in rows:
            result.setdefault(row['mentor'], []).append(row['mentee'])
        return result


def get_last_digest_time():
    with connect() as conn:
        row = conn.execute(
            "SELECT value FROM digest_meta WHERE key = 'last_digest_time'",
        ).fetchone()
        return row['value'] if row else None


def set_last_digest_time(timestamp=None):
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO digest_meta (key, value) VALUES (?, ?)",
            ('last_digest_time', timestamp or _now()),
        )
