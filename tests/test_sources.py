import unittest
from unittest import mock

from src.sources import JobSources, title_matches, location_ok, DEFAULT_TARGET_TITLES
from src.db import get_connection
from tests.helpers import Env


class FakeResp:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status

    def json(self):
        return self._data


class TestSources(unittest.TestCase):
    def test_title_matching(self):
        for t in ("Forward Deployed Product Manager", "Product Manager, Forward-Deployed (Fintech)",
                  "Senior Forward Deployed PM", "Appian Forward Deployed Product Owner", "Deployed Product Manager"):
            self.assertTrue(title_matches(t, DEFAULT_TARGET_TITLES), t)
        for t in ("Forward Deployed Engineer", "Senior Product Manager", "Hotel Manager"):
            self.assertFalse(title_matches(t, DEFAULT_TARGET_TITLES), t)

    def test_location_filter(self):
        self.assertTrue(location_ok("San Francisco, CA"))
        self.assertTrue(location_ok("Remote (US)"))
        self.assertTrue(location_ok("New York | London"))
        self.assertFalse(location_ok("London, UK"))
        self.assertFalse(location_ok("Toronto"))

    def test_discover_ingests_only_matching_roles(self):
        env = Env(with_resumes=False)
        responses = {
            "boards-api.greenhouse.io": FakeResp({"jobs": [
                {"id": 1, "title": "Forward Deployed Product Manager", "location": {"name": "New York"},
                 "content": "&lt;p&gt;Own customer outcomes&lt;/p&gt;", "company_name": "Acme"},
                {"id": 2, "title": "Forward Deployed Engineer", "location": {"name": "New York"}, "content": ""}]}),
            "api.lever.co": FakeResp([], 404),
            "api.ashbyhq.com": FakeResp({"jobs": [
                {"id": "a1", "title": "Forward Deployed PM, Financial Services", "location": "London", "isListed": True},
                {"id": "a2", "title": "Forward Deployed PM, Financial Services", "location": "San Francisco",
                 "isListed": True, "jobUrl": "https://jobs.ashbyhq.com/ode/a2"}]}),
        }
        session = mock.Mock(headers={})
        session.get.side_effect = lambda url, timeout: next(v for k, v in responses.items() if k in url)
        src = JobSources(db_path=env.db_path, data_dir=env.data_dir, session=session)
        src.save({"greenhouse": ["acme"], "lever": ["nobody"], "ashby": ["ode"]})
        out = src.discover()
        self.assertEqual(out["new"], 2)
        conn = get_connection(env.db_path)
        rows = {r["company"]: dict(r) for r in conn.execute("SELECT * FROM jobs").fetchall()}
        conn.close()
        self.assertEqual(rows["Acme"]["posting_url"], "https://job-boards.greenhouse.io/acme/jobs/1")
        self.assertEqual(rows["Acme"]["platform_type"], "greenhouse")
        self.assertEqual(rows["Acme"]["description_raw"], "Own customer outcomes")
        self.assertEqual(rows["Ode"]["platform_type"], "ashby")
        env.close()


if __name__ == "__main__":
    unittest.main()
