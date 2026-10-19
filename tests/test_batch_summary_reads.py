"""Summary reads keep business fields without reconstructing full task results."""
import unittest
from unittest.mock import patch

from sqlalchemy import text
import test_business_api as base


class BatchSummaryReadTests(unittest.TestCase):
    setUp = base.BusinessAPITests.setUp

    def test_summary_works_without_result_projection_or_export_validation(self):
        created = self.business.store.create_batch([
            dict(data=self.image + bytes([i]), name='synthetic.png', mime='image/png')
            for i in range(3)], ['DIPLOMA', 'DEGREE_CERT', 'DIPLOMA'], 'synthetic')
        batch_id = created['batch_id']
        with self.business.store.transaction() as connection:
            for task_id, status in zip(created['task_ids'], ['COMPLETED', 'NEED_REVIEW', 'FAILED']):
                connection.execute(text('UPDATE tasks SET status=:status WHERE id=:id'), dict(id=task_id, status=status))
        before = self.business.store.batch(batch_id)
        with patch.object(self.business.store, '_public', side_effect=AssertionError('Summary must not project results')):
            self.assertEqual(self.business.store.batch(batch_id), before)
            self.assertEqual(self.business.store.batches()['items'], [before])
        self.assertEqual((before['completed_count'], before['need_review_count'], before['failed_count']), (1, 1, 1))
        self.assertTrue(before['name'].endswith('混合材料 · 毕业证 / 学位证'))

