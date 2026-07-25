# Development tasks.
#
# `make test` mirrors exactly what CI runs, so local and CI stay in sync.
# PYWIKIBOT_NO_USER_CONFIG=1 is required because notifications.py imports
# pywikibot at load time and there may be no user-config.py present.

.PHONY: test lint install

test:
	PYWIKIBOT_NO_USER_CONFIG=1 python -m unittest test_parsing.py test_notifications.py test_db.py

lint:
	ruff check .

install:
	pip install -r requirements.txt
