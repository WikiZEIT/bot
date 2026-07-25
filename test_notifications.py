#!/usr/bin/env python
# Copyright (C) 2026 Jakub T. Jankiewicz <https://jakub.jankiewicz.org/>
#
# Licensed under the GNU AGPL v3 or later. See LICENSE.

"""Tests for the per-mentor email opt-in logic in `notifications.py`.

Covers the pure helpers that decide which mentors get their own newcomer
summary (`email=tak` opt-in) and how that summary is rendered. The actual
send goes through pywikibot's emailuser API and is not exercised here.

Run: `python -m unittest test_notifications.py`.
"""

import unittest
from unittest import mock

import notifications
from notifications import (
    NotificationManager,
    contribs_url,
    email_optin,
    format_mentor_results,
    format_mentor_summary,
    select_mentor_recipients,
)


class EmailOptinTests(unittest.TestCase):
    def test_tak_opts_in(self):
        self.assertTrue(email_optin({'email': 'tak'}))

    def test_case_insensitive(self):
        self.assertTrue(email_optin({'email': 'Tak'}))
        self.assertTrue(email_optin({'email': 'TAK'}))

    def test_surrounding_whitespace(self):
        self.assertTrue(email_optin({'email': ' tak '}))

    def test_missing_flag_opts_out(self):
        self.assertFalse(email_optin({'przewodnik': 'Foo'}))

    def test_other_value_opts_out(self):
        self.assertFalse(email_optin({'email': 'nie'}))

    def test_none_params_opts_out(self):
        self.assertFalse(email_optin(None))


class SelectMentorRecipientsTests(unittest.TestCase):
    def setUp(self):
        self.stored = {
            'Alice': {'przewodnik': 'Alice', 'email': 'tak'},
            'Bob': {'przewodnik': 'Bob'},              # no opt-in
            'Carol': {'przewodnik': 'Carol', 'email': 'nie'},
            'Dave': {'przewodnik': 'Dave', 'email': 'Tak'},
        }

    def _get_params(self, mentor):
        return self.stored.get(mentor)

    def test_only_opted_in_mentors_with_newcomers(self):
        newcomers = {
            'Alice': ['Ann', 'Amy'],
            'Bob': ['Ben'],
            'Dave': ['Don'],
        }
        result = dict(select_mentor_recipients(newcomers, self._get_params))
        self.assertEqual(set(result), {'Alice', 'Dave'})
        self.assertEqual(result['Alice'], ['Ann', 'Amy'])
        self.assertEqual(result['Dave'], ['Don'])

    def test_opted_in_mentor_without_newcomers_excluded(self):
        # Carol opted out anyway; Alice opted in but has no newcomers here.
        newcomers = {'Bob': ['Ben']}
        self.assertEqual(select_mentor_recipients(newcomers, self._get_params), [])

    def test_mentor_missing_from_store_skipped(self):
        newcomers = {'Zoe': ['Zack']}
        self.assertEqual(select_mentor_recipients(newcomers, self._get_params), [])

    def test_empty_name_list_skipped(self):
        newcomers = {'Alice': []}
        self.assertEqual(select_mentor_recipients(newcomers, self._get_params), [])


class FormatMentorSummaryTests(unittest.TestCase):
    SINCE = '2026-07-01T00:00:00+00:00'
    PAGE_URL = 'https://pl.wikipedia.org/wiki/Pomoc:Przewodnicy/Podopieczni/Jcubic'

    def test_contains_newcomers_count_and_since(self):
        body = format_mentor_summary('Alice', ['Ann', 'Amy'], self.SINCE, self.PAGE_URL)
        self.assertIn('Alice', body)
        self.assertIn('Ann', body)
        self.assertIn('Amy', body)
        self.assertIn(self.SINCE, body)
        self.assertIn('2', body)  # count of newcomers

    def test_only_newcomers_listed_not_full_roster(self):
        # The mail lists only the newcomers passed in — a mentor may have
        # thousands of mentees, so the roster is intentionally left out.
        body = format_mentor_summary('Alice', ['Ann'], self.SINCE, self.PAGE_URL)
        self.assertIn('Ann', body)
        self.assertNotIn('Old', body)

    def test_single_newcomer(self):
        body = format_mentor_summary('Dave', ['Don'], self.SINCE, self.PAGE_URL)
        self.assertIn('Don', body)

    def test_includes_contribs_url_per_newcomer(self):
        body = format_mentor_summary('Alice', ['Ann', 'Amy'], self.SINCE, self.PAGE_URL)
        self.assertIn('https://pl.wikipedia.org/wiki/Specjalna:Wkład/Ann', body)
        self.assertIn('https://pl.wikipedia.org/wiki/Specjalna:Wkład/Amy', body)

    def test_name_then_url_line_format(self):
        # Each newcomer: a name line, then a `* <url>` line beneath it.
        body = format_mentor_summary('Alice', ['Ann'], self.SINCE, self.PAGE_URL)
        self.assertIn('Ann\n* https://pl.wikipedia.org/wiki/Specjalna:Wkład/Ann', body)

    def test_uses_provided_page_url_verbatim(self):
        # The mentee-list link is the actual page URL, not a constructed one.
        body = format_mentor_summary('jcubic', ['Ann'], self.SINCE, self.PAGE_URL)
        self.assertIn(f'* {self.PAGE_URL}', body)

    def test_no_page_url_omits_list_link(self):
        body = format_mentor_summary('jcubic', ['Ann'], self.SINCE, None)
        self.assertNotIn('Pełną listę', body)


class ContribsUrlTests(unittest.TestCase):
    def test_simple_name(self):
        self.assertEqual(
            contribs_url('Jcubic'),
            'https://pl.wikipedia.org/wiki/Specjalna:Wkład/Jcubic',
        )

    def test_spaces_become_underscores(self):
        self.assertEqual(
            contribs_url('Jan Kowalski'),
            'https://pl.wikipedia.org/wiki/Specjalna:Wkład/Jan_Kowalski',
        )


class FakeUser:
    """Stand-in for pywikibot.User capturing send_email calls.

    Behaviour is driven by the module-level EMAILABLE / SEND_OUTCOME maps so
    each test can script a mentor as emailable/not, and the send as
    success/False/raising."""
    sent = []

    def __init__(self, site, name):
        self.name = name

    def isEmailable(self):  # noqa: N802 — mirrors pywikibot's API name
        return EMAILABLE.get(self.name, False)

    def send_email(self, subject, text):
        FakeUser.sent.append((self.name, subject, text))
        outcome = SEND_OUTCOME.get(self.name, True)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


EMAILABLE = {}
STORED_PARAMS = {}
STORED_PAGE_URL = {}  # mentor -> mentee-list page URL
SEND_OUTCOME = {}  # mentor -> True / False / Exception instance


class SendMentorDigestsTests(unittest.TestCase):
    def setUp(self):
        FakeUser.sent = []
        EMAILABLE.clear()
        STORED_PARAMS.clear()
        STORED_PAGE_URL.clear()
        SEND_OUTCOME.clear()

    def _run(self, newcomers, since='2026-07-01T00:00:00+00:00'):
        manager = NotificationManager(enabled=True)
        with mock.patch.object(notifications.pywikibot, 'User', FakeUser), \
             mock.patch.object(notifications.db, 'get_params', STORED_PARAMS.get), \
             mock.patch.object(notifications.db, 'get_page_url', STORED_PAGE_URL.get):
            results = manager._send_mentor_digests(
                site=object(), newcomers=newcomers, since=since)
        return manager, results

    def _status(self, results, mentor):
        for r in results:
            if r['mentor'] == mentor:
                return r['status']
        return None

    def test_opted_in_emailable_mentor_receives_summary(self):
        STORED_PARAMS['Alice'] = {'email': 'tak'}
        STORED_PAGE_URL['Alice'] = 'https://pl.wikipedia.org/wiki/Pomoc:Przewodnicy/Podopieczni/Alice'
        EMAILABLE['Alice'] = True
        _, results = self._run({'Alice': ['Ann', 'Amy']})
        self.assertEqual(len(FakeUser.sent), 1)
        name, subject, text = FakeUser.sent[0]
        self.assertEqual(name, 'Alice')
        self.assertEqual(subject, notifications.MENTOR_SUBJECT)
        self.assertIn('Ann', text)
        self.assertIn('Amy', text)
        self.assertIn(STORED_PAGE_URL['Alice'], text)  # page URL from the DB
        self.assertEqual(self._status(results, 'Alice'), 'sent')

    def test_opted_out_mentor_not_contacted(self):
        STORED_PARAMS['Bob'] = {'przewodnik': 'Bob'}
        EMAILABLE['Bob'] = True
        _, results = self._run({'Bob': ['Ben']})
        self.assertEqual(FakeUser.sent, [])
        self.assertEqual(results, [])

    def test_non_emailable_mentor_skipped(self):
        STORED_PARAMS['Carol'] = {'email': 'tak'}
        EMAILABLE['Carol'] = False
        _, results = self._run({'Carol': ['Cara']})
        self.assertEqual(FakeUser.sent, [])
        self.assertEqual(self._status(results, 'Carol'), 'skipped')

    def test_send_raises_is_reported_as_failed_not_crash(self):
        # E.g. the bot account itself has no confirmed e-mail — send raises.
        STORED_PARAMS['Dave'] = {'email': 'tak'}
        EMAILABLE['Dave'] = True
        SEND_OUTCOME['Dave'] = RuntimeError('bot ma niepotwierdzony e-mail')
        _, results = self._run({'Dave': ['Don']})
        self.assertEqual(self._status(results, 'Dave'), 'failed')

    def test_send_returning_false_is_failed(self):
        STORED_PARAMS['Eve'] = {'email': 'tak'}
        EMAILABLE['Eve'] = True
        SEND_OUTCOME['Eve'] = False
        _, results = self._run({'Eve': ['Ela']})
        self.assertEqual(self._status(results, 'Eve'), 'failed')

    def test_one_failure_does_not_block_others(self):
        STORED_PARAMS['Alice'] = {'email': 'tak'}
        STORED_PARAMS['Carol'] = {'email': 'tak'}
        EMAILABLE['Alice'] = True
        EMAILABLE['Carol'] = False  # skipped, but Alice must still be mailed
        self._run({'Carol': ['Cara'], 'Alice': ['Ann']})
        self.assertEqual([n for n, _, _ in FakeUser.sent], ['Alice'])


class FormatMentorResultsTests(unittest.TestCase):
    def test_empty_results_render_nothing(self):
        self.assertEqual(format_mentor_results([]), "")

    def test_counts_and_names_appear(self):
        results = [
            {'mentor': 'Alice', 'status': 'sent', 'detail': '2 nowych'},
            {'mentor': 'Carol', 'status': 'skipped', 'detail': 'nie przyjmuje e-maili'},
            {'mentor': 'Dave', 'status': 'failed', 'detail': 'RuntimeError: boom'},
        ]
        text = format_mentor_results(results)
        self.assertIn('1 wysłane', text)
        self.assertIn('1 pominięte', text)
        self.assertIn('1 błędne', text)
        self.assertIn('Alice', text)
        self.assertIn('Carol', text)
        self.assertIn('Dave', text)

    def test_appears_in_full_digest_body(self):
        manager = NotificationManager(enabled=True)
        entries = [{'started': 'A', 'finished': 'B', 'pages_processed': 1,
                    'writes_succeeded': 1, 'updated_pages': [], 'errors': []}]
        results = [{'mentor': 'Alice', 'status': 'sent', 'detail': '1 nowych'}]
        body = manager._format_digest(
            entries, newcomers={}, since='A', mentor_results=results)
        self.assertIn('Powiadomienia', body)
        self.assertIn('Alice', body)


if __name__ == '__main__':
    unittest.main()
