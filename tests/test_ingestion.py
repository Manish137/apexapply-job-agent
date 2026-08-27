import unittest
import tempfile
from pathlib import Path

from src.db import init_db, get_connection
from src.ingestion import IngestionService

class TestIngestion(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_ingestion.db"
        init_db(self.db_path)
        self.service = IngestionService(db_path=self.db_path)
        self.fixture_path = Path(__file__).parent / "fixtures" / "sample_jobs.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_ingestion_and_deduplication(self):
        # 1. First run should insert 3 jobs
        new_c, dup_c = self.service.ingest_file(self.fixture_path)
        self.assertEqual(new_c, 3)
        self.assertEqual(dup_c, 0)

        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as c FROM jobs")
        self.assertEqual(cursor.fetchone()["c"], 3)

        # Check platform detection
        cursor.execute("SELECT company, platform_type FROM jobs ORDER BY company")
        rows = cursor.fetchall()
        self.assertEqual(rows[0]["company"], "Anthropic")
        self.assertEqual(rows[0]["platform_type"], "greenhouse")
        self.assertEqual(rows[1]["company"], "Stripe")
        self.assertEqual(rows[1]["platform_type"], "lever")
        self.assertEqual(rows[2]["company"], "Workday Labs")
        self.assertEqual(rows[2]["platform_type"], "workday")
        conn.close()

        # 2. Second run on same fixture should reject all 3 as duplicates
        new_c2, dup_c2 = self.service.ingest_file(self.fixture_path)
        self.assertEqual(new_c2, 0)
        self.assertEqual(dup_c2, 3)

if __name__ == "__main__":
    unittest.main()
