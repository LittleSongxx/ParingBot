"""检索后端健康度 + 并行召回契约测试（ADR-0012：monitor→路由闭环）。"""
import unittest
from unittest.mock import patch

from smartlect.knowledge import BackendHealth, _recall_backends


class BackendHealthTests(unittest.TestCase):
    def test_consecutive_failures_trigger_skip_and_success_resets(self):
        health = BackendHealth(failure_threshold=3, retry_after_seconds=60.0)
        for _ in range(2):
            health.record('es_bm25', False)
        self.assertFalse(health.should_skip('es_bm25'))
        health.record('es_bm25', False)
        self.assertTrue(health.should_skip('es_bm25'))
        # 成功一次即恢复
        health.record('es_bm25', True)
        self.assertFalse(health.should_skip('es_bm25'))

    def test_skip_window_expires_to_half_open_probe(self):
        health = BackendHealth(failure_threshold=2, retry_after_seconds=0.05)
        health.record('qdrant_ann', False)
        health.record('qdrant_ann', False)
        self.assertTrue(health.should_skip('qdrant_ann'))
        health.note_skipped('qdrant_ann')
        import time as _time
        _time.sleep(0.06)
        # 半开：窗口过后放行真实请求
        self.assertFalse(health.should_skip('qdrant_ann'))

    def test_failed_probe_re_arms_skip_without_probe_storm(self):
        # 半开探测失败后：下一次评估必须回到跳过态——否则窗口过期后
        # 每次请求都会打故障后端（探测风暴）。
        import time as _time
        health = BackendHealth(failure_threshold=2, retry_after_seconds=0.05)
        health.record('es_bm25', False)
        health.record('es_bm25', False)
        self.assertTrue(health.should_skip('es_bm25'))
        health.note_skipped('es_bm25')
        _time.sleep(0.06)
        self.assertFalse(health.should_skip('es_bm25'))   # 放行探测
        health.record('es_bm25', False)                    # 探测失败
        self.assertTrue(health.should_skip('es_bm25'))     # 重新进入跳过态

    def test_note_skipped_does_not_refresh_active_window(self):
        # 调用方每次跳过都调 note_skipped：活动窗口内刷新时间戳会让窗口
        # 永不过期（_vendor_rerank_order 的每请求调用形态）。
        import time as _time
        health = BackendHealth(failure_threshold=1, retry_after_seconds=0.06)
        health.record('vendor_rerank', False)
        self.assertTrue(health.should_skip('vendor_rerank'))
        health.note_skipped('vendor_rerank')
        _time.sleep(0.03)
        health.note_skipped('vendor_rerank')  # 窗口内的重复调用不得续期
        _time.sleep(0.04)
        self.assertFalse(health.should_skip('vendor_rerank'))  # 原窗口已过期 → 允许探测

    def test_intermittent_failures_do_not_degrade(self):
        health = BackendHealth(failure_threshold=3)
        for ok in (False, True, False, True, False):
            health.record('vendor_rerank', ok)
        self.assertFalse(health.should_skip('vendor_rerank'))
        self.assertEqual(health.snapshot(('vendor_rerank',))['vendor_rerank']['state'], 'ok')

    def test_snapshot_reports_degraded_state(self):
        health = BackendHealth(failure_threshold=2)
        health.record('es_bm25', False)
        health.record('es_bm25', False)
        report = health.snapshot(('es_bm25',))
        self.assertEqual(report['es_bm25']['state'], 'degraded')
        self.assertEqual(report['es_bm25']['recent_failures'], 2)


class ParallelRecallTests(unittest.TestCase):
    def setUp(self):
        # _BACKEND_HEALTH 是模块级状态；每个用例换成全新实例避免跨测试污染。
        self._fresh = BackendHealth()
        patcher = patch('smartlect.knowledge._BACKEND_HEALTH', self._fresh)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_recall_runs_both_backends_in_parallel_and_passes_through(self):
        async def fake_ann(query_vector, scope, model, index_version, limit):
            return [{'doc_id': 'd', 'version': 1, 'chunk_id': 'c1', 'score': 0.9}], 'qdrant_hnsw'

        async def fake_bm25(query, scope, extra_queries=None):
            return [(('d', 1, 'c1'), 3.2)], 'es_bm25_ik'

        with patch('smartlect.hybrid_search.ann_search', fake_ann), \
             patch('smartlect.hybrid_search.bm25_search', fake_bm25), \
             patch('smartlect.hybrid_search.qdrant_client', return_value=object()), \
             patch('smartlect.hybrid_search.es_client', return_value=object()):
            (dense, vector_backend), (es_hits, es_backend), health = _recall_backends(
                'scope', [0.1, 0.2], 'text-embedding-v4', 'v1', '键盘', None, None)
        self.assertEqual(dense[0]['chunk_id'], 'c1')
        self.assertEqual(vector_backend, 'qdrant_hnsw')
        self.assertEqual(es_backend, 'es_bm25_ik')
        self.assertIn('es_bm25', health)
        self.assertIn('qdrant_ann', health)

    def test_degraded_backend_is_skipped_without_call(self):
        calls = []

        async def fake_ann(*args, **kwargs):
            calls.append('ann')
            return [], 'qdrant_hnsw'

        async def fake_bm25(*args, **kwargs):
            calls.append('bm25')
            return None, 'es_bm25_ik'

        with patch.object(self._fresh, 'should_skip',
                          side_effect=lambda name, now=None: name == 'es_bm25'), \
             patch('smartlect.hybrid_search.ann_search', fake_ann), \
             patch('smartlect.hybrid_search.bm25_search', fake_bm25), \
             patch('smartlect.hybrid_search.qdrant_client', return_value=object()), \
             patch('smartlect.hybrid_search.es_client', return_value=object()):
            (dense, vector_backend), (es_hits, es_backend), _ = _recall_backends(
                'scope', [0.1], 'text-embedding-v4', 'v1', '键盘', None, None)
        self.assertEqual(calls, ['ann'])  # 被降权的 ES 不发请求
        self.assertEqual(es_backend, 'skipped_degraded')
        self.assertIsNone(es_hits)
        self.assertEqual(dense, [])  # fake ann 返回空列表 → 记为失败

    def test_no_vector_metadata_means_ann_unused(self):
        (dense, vector_backend), (es_hits, es_backend), _ = _recall_backends(
            'scope', None, None, None, '键盘', None, None)
        self.assertEqual(dense, [])
        self.assertEqual(vector_backend, 'unused')


if __name__ == "__main__":
    unittest.main()
