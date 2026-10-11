"""Source integrity checks using explicitly synthetic API fixtures."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import public_collector as collector
from deepseek_client import ResearchError
from deepseek_research import normalize_comments


class CollectorTests(unittest.TestCase):
    def test_only_actual_reply_body_is_a_quote(self):
        replies = [{'id': 10, 'content': '@someone synthetic comment', 'created': 1609459200,
                    'member': {'username': 'must-not-store', 'email': 'private@example.test'}}]
        with patch.object(collector, 'read_json', side_effect=[
            {'hits': [{'_source': {'id': 123, 'content': 'search snippet must not become a quote'}}]},
            [{'id': 123, 'title': 'Synthetic topic'}], replies]):
            result = collector.collect('test', ['test'])
        rows, audit = normalize_comments(result)
        self.assertEqual(rows[0]['quote'], '@匿名用户 synthetic comment')
        self.assertEqual(rows[0]['source_url'], 'https://www.v2ex.com/t/123#r_10')
        self.assertEqual(rows[0]['published_at'], '2021-01-01')
        self.assertNotIn('must-not-store', str(result))
        self.assertNotIn('search snippet', str(result))
        self.assertTrue(any(a['sample_ids']=='R0001' for a in audit))

    def test_search_failure_is_audited_and_never_retried(self):
        with patch.object(collector, 'read_json', side_effect=ResearchError('HTTP 403 denied')) as read:
            result = collector.collect('test', ['first', 'second'])
        self.assertEqual(read.call_count, 1)
        self.assertEqual(result['comments'], [])
        self.assertIn('403', result['sources'][0]['decision'])
        normalize_comments(result)

    def test_direct_topic_still_fetches_original_reply_not_user_supplied_text(self):
        with patch.object(collector, 'read_json', side_effect=[[{'id': 123, 'title': 'Synthetic'}], []]) as read:
            result = collector.collect('https://www.v2ex.com/t/123', [])
        self.assertEqual(read.call_count, 2)
        self.assertEqual(result['comments'], [])
        normalize_comments(result)

    def test_contact_redaction_and_length_limits(self):
        self.assertNotIn('13812345678', collector.anonymous_quote('联系13812345678'))
        self.assertNotIn('test@example.com', collector.anonymous_quote('联系 test@example.com'))
        self.assertEqual(collector.anonymous_quote('a'*12001), '')

    def test_network_host_allowlist(self):
        for url in ['https://127.0.0.1/api', 'http://www.v2ex.com/api', 'https://www.v2ex.com.evil.example/api']:
            with self.assertRaises(ResearchError):
                collector.read_json(url, 999999999999)


if __name__ == '__main__':
    unittest.main()
