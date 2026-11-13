import datetime as dt
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import urllib.error
import urllib.parse
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('tested_usage_report', ROOT / 'tools/usage_report.py')
usage = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {'common': SimpleNamespace(WORK_DIR=str(ROOT), CFG={})}):
    spec.loader.exec_module(usage)

NOW = dt.datetime(2026, 11, 14, 0, 30, tzinfo=dt.timezone(dt.timedelta(hours=8)))


def bucket(day, value=None, currency='usd'):
    start = dt.datetime.fromisoformat(day).replace(tzinfo=dt.timezone.utc)
    return {'start_time': int(start.timestamp()), 'end_time': int(start.timestamp()) + 86400,
            'results': [] if value is None else [{'amount': {'value': value, 'currency': currency}}]}


def page(*buckets, more=False, cursor=None):
    return {'data': list(buckets), 'has_more': more, 'next_page': cursor}


class UsageReportTests(unittest.TestCase):
    def setUp(self):
        self.network = patch.object(usage, '_request_json', side_effect=AssertionError('unexpected network'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def fetch(self, payload):
        with patch.object(usage, '_request_json', return_value=payload) as request:
            result = usage.fetch_platform_costs('fixture-admin-key', now=NOW)
        return result, request

    def test_utc_month_query_excludes_previous_month_bucket(self):
        result, request = self.fetch(page(bucket('2026-10-31', 99), bucket('2026-11-01', 2)))
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.call_args.args[0]).query)
        self.assertEqual(int(query['start_time'][0]), int(dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc).timestamp()))
        self.assertEqual(int(query['end_time'][0]), int(NOW.timestamp()))
        self.assertEqual(result['cost'], 2)
        self.assertEqual(result['period_timezone'], 'UTC')
        self.assertEqual(result['query_end'], '2026-11-13T16:30:00Z')
        self.assertEqual(result['excluded_buckets'], 1)

    def test_all_pages_and_empty_buckets_do_not_advance_cost_result_date(self):
        with patch.object(usage, '_request_json', side_effect=[
                page(bucket('2026-11-01', .25), more=True, cursor='next/cursor'),
                page(bucket('2026-11-12', 2), bucket('2026-11-13'))]) as request:
            result = usage.fetch_platform_costs('fixture', now=NOW)
        self.assertEqual(result['cost'], 2.25)
        self.assertEqual(result['last_cost_date'], '2026-11-12')
        self.assertEqual(result['last_bucket_date'], '2026-11-13')
        self.assertEqual(result['empty_buckets'], 1)
        self.assertEqual(result['pages'], 2)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.call_args.args[0]).query)
        self.assertEqual(query['page'], ['next/cursor'])

    def test_repeating_cursor_never_returns_partial_total(self):
        with patch.object(usage, '_request_json', side_effect=[
                page(bucket('2026-11-01', 1), more=True, cursor='same'),
                page(bucket('2026-11-02', 2), more=True, cursor='same')]):
            result = usage.fetch_platform_costs('fixture', now=NOW)
        self.assertIn('error', result)
        self.assertNotIn('cost', result)

    def test_identical_page_overlap_is_counted_once(self):
        item = bucket('2026-11-01', 1)
        with patch.object(usage, '_request_json', side_effect=[
                page(item, more=True, cursor='next'), page(item, bucket('2026-11-02', 2))]):
            result = usage.fetch_platform_costs('fixture', now=NOW)
        self.assertEqual(result['cost'], 3)

    def test_conflicting_page_overlap_is_unavailable(self):
        with patch.object(usage, '_request_json', side_effect=[
                page(bucket('2026-11-01', 1), more=True, cursor='next'),
                page(bucket('2026-11-01', 9))]):
            result = usage.fetch_platform_costs('fixture', now=NOW)
        self.assertIn('error', result)
        self.assertNotIn('cost', result)

    def test_zero_amount_is_a_result_but_empty_bucket_is_not(self):
        result, _ = self.fetch(page(bucket('2026-11-12', 0), bucket('2026-11-13')))
        self.assertTrue(result['has_cost_results'])
        self.assertEqual(result['last_cost_date'], '2026-11-12')
        result, _ = self.fetch(page(bucket('2026-11-13')))
        self.assertFalse(result['has_cost_results'])
        self.assertIsNone(result['last_cost_date'])

    def test_invalid_amount_currency_or_pagination_fails_closed(self):
        for payload in [page(bucket('2026-11-01', float('nan'))),
                        page(bucket('2026-11-01', True)),
                        page(bucket('2026-11-01', 1, 'usd'), bucket('2026-11-02', 1, 'eur')),
                        {'data': [], 'has_more': True, 'next_page': None}]:
            with self.subTest(payload=payload):
                result, _ = self.fetch(payload)
                self.assertIn('error', result)
                self.assertNotIn('cost', result)

    def test_http_error_does_not_copy_response_body_or_credentials(self):
        error = urllib.error.HTTPError('https://fixture', 403, 'private diagnostic', {}, None)
        with patch.object(usage, '_request_json', side_effect=error):
            result = usage.fetch_platform_costs('fixture-admin-key', now=NOW)
        self.assertEqual(result, {'error': 'Platform costs HTTP 403'})
        self.assertNotIn('private', json.dumps(result))

    def test_report_reference_difference_is_not_a_pro_balance(self):
        platform, _ = self.fetch(page(bucket('2026-11-12', 25)))
        with patch.object(usage, '_config', return_value={'OPENAI_ADMIN_KEY': 'fixture', 'OPENAI_PRO_CREDIT': '100'}), \
                patch.object(usage, 'fetch_chatgpt_usage', return_value={'error': 'fixture'}), \
                patch.object(usage, 'fetch_platform_costs', return_value=platform), \
                patch.object(usage, '_write_cache'):
            report = usage.build_report()
        self.assertEqual(report['platform']['reference_difference'], 75)
        self.assertIsNone(report['platform']['remaining'])
        text = usage.format_text(report)
        self.assertIn('UTC', text)
        self.assertIn('2026-11-12', text)
        self.assertIn('非余额', text)
        self.assertNotIn('预计剩余', text)

    def test_invalid_reference_credit_does_not_create_a_balance(self):
        for credit in ['nan', 'inf', '-10', 'invalid']:
            platform, _ = self.fetch(page(bucket('2026-11-12', 25)))
            with patch.object(usage, '_config', return_value={'OPENAI_ADMIN_KEY': 'fixture', 'OPENAI_PRO_CREDIT': credit}), \
                    patch.object(usage, 'fetch_chatgpt_usage', return_value={'error': 'fixture'}), \
                    patch.object(usage, 'fetch_platform_costs', return_value=platform), \
                    patch.object(usage, '_write_cache'):
                report = usage.build_report()
            self.assertIsNone(report['platform']['reference_difference'])
            json.dumps(report, allow_nan=False)

    def test_cache_preserves_period_and_actual_result_freshness(self):
        platform, _ = self.fetch(page(bucket('2026-11-12', 2), bucket('2026-11-13')))
        with tempfile.TemporaryDirectory(dir=ROOT, prefix='synthetic-usage-') as folder:
            cache = Path(folder) / 'usage.json'
            with patch.object(usage, 'CACHE_PATH', cache):
                usage._write_cache({'platform': platform, 'credit_grants': {}})
            value = json.loads(cache.read_text(encoding='utf-8'))
        self.assertEqual(value['version'], 2)
        self.assertEqual(value['period_timezone'], 'UTC')
        self.assertEqual(value['last_cost_date'], '2026-11-12')
        self.assertEqual(value['last_bucket_date'], '2026-11-13')
        self.assertEqual(value['fetched_at'], '2026-11-13T16:30:00Z')


if __name__ == '__main__':
    unittest.main()
