#!/usr/bin/env python
# Copyright (C) 2026 Jakub T. Jankiewicz <https://jakub.jankiewicz.org/>
#
# Licensed under the GNU AGPL v3 or later. See LICENSE.

"""Tests for `db.py` — focused on the `page_url` column: the schema migration
that adds it to a pre-existing database, and the store/read round-trip.

Run: `python -m unittest test_db.py`.
"""

import os
import shutil
import sqlite3
import tempfile
import unittest

import db


class PageUrlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig_dir, self._orig_path = db.DB_DIR, db.DB_PATH
        db.DB_DIR = self.tmp
        db.DB_PATH = os.path.join(self.tmp, 'bot.db')

    def tearDown(self):
        db.DB_DIR, db.DB_PATH = self._orig_dir, self._orig_path
        shutil.rmtree(self.tmp)

    def test_store_and_read_round_trip(self):
        db.run_migrations()
        url = 'https://pl.wikipedia.org/wiki/Pomoc:Przewodnicy/Podopieczni/Jcubic'
        db.update_mentor('jcubic', {'przewodnik': 'jcubic'}, ['Ann'], page_url=url)
        self.assertEqual(db.get_page_url('jcubic'), url)

    def test_unknown_mentor_returns_none(self):
        db.run_migrations()
        self.assertIsNone(db.get_page_url('nobody'))

    def test_migration_adds_column_to_old_database(self):
        # Build a database with the pre-page_url schema and NO schema_migrations
        # table, as it exists in production, then let the migration runner bring
        # it up to date without error.
        conn = sqlite3.connect(db.DB_PATH)
        conn.execute(
            "CREATE TABLE mentor_params "
            "(mentor TEXT PRIMARY KEY, params_json TEXT, updated TEXT)"
        )
        conn.execute(
            "INSERT INTO mentor_params (mentor, params_json, updated) VALUES (?, ?, ?)",
            ('old', '{}', '2020-01-01T00:00:00+00:00'),
        )
        conn.commit()
        conn.close()

        db.run_migrations()
        # No page_url yet for the legacy row — must not raise.
        self.assertIsNone(db.get_page_url('old'))
        # And the column is now writable.
        db.update_mentor('old', {}, [], page_url='https://x')
        self.assertEqual(db.get_page_url('old'), 'https://x')

    def test_all_migrations_recorded(self):
        db.run_migrations()
        with db.connect() as conn:
            recorded = db.applied_versions(conn)
        self.assertEqual(recorded, {v for v, _ in db.MIGRATIONS})

    def test_run_migrations_is_idempotent(self):
        first = db.run_migrations()
        second = db.run_migrations()
        # Same final version set, and the second run raises nothing.
        self.assertEqual(first, second)
        self.assertEqual(first, sorted(v for v, _ in db.MIGRATIONS))


if __name__ == '__main__':
    unittest.main()
