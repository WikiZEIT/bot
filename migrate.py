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

"""Apply pending database schema migrations, then report the schema version.

Run from the deploy workflow after pulling code, and safe to run by hand:

    python migrate.py

Any pending migration that fails raises, so the deploy step fails loudly rather
than leaving the database half-migrated.
"""

import db


def main():
    # Any migration actually applied prints its own `[db] Zastosowano migrację N`
    # line; this reports the resulting full set of applied versions.
    versions = db.run_migrations()
    if versions:
        print(f"Baza danych aktualna (wszystkie migracje: {versions}).")
    else:
        print("Baza danych: brak zdefiniowanych migracji.")


if __name__ == '__main__':
    main()
