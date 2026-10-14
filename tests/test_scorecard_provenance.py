"""Fingerprint covers the full market state that can influence a scan/outcome."""
import unittest
from stockex.backtest.scorecard import data_fingerprint
from stockex.market.schema import open_market_db


class FingerprintTests(unittest.TestCase):
    def setUp(self):
        self.db = open_market_db(':memory:')

    def tearDown(self):
        self.db.close()

    def fingerprint(self):
        return data_fingerprint(self.db, '2025-01-01', '2025-02-01')

    def test_every_market_input_table_changes_the_snapshot(self):
        statements = [
            "INSERT INTO bars VALUES ('ABC','EQ','2025-03-01',10,11,9,10,10,100,1000,10,50,50,'isin','2025-03-01T12:00:00Z')",
            "INSERT INTO index_bars VALUES ('NIFTY','2025-01-01',10,11,9,10,'2025-01-01T12:00:00Z')",
            "INSERT INTO fo_bars VALUES ('ABC','CE','2025-03-01',100,'2025-01-01',10,11,9,10,10,100,10,1,5,0,'2025-01-01T12:00:00Z')",
            "INSERT INTO deals VALUES ('BULK','2025-01-01','ABC','Fund','BUY',10,100,'2025-01-01T12:00:00Z')",
            "INSERT INTO corporate_actions VALUES ('ABC','2025-01-01','SPLIT',.5,'split','2025-01-01T12:00:00Z')",
            "INSERT INTO index_members VALUES ('NIFTY','ABC','BANKS','isin','2025-01-01')",
            "INSERT INTO announcements VALUES ('ABC','2025-01-01T10:00:00Z','Results','details','RESULTS','EXCHANGE')",
            "INSERT INTO restrictions VALUES ('ASM','ABC','1','2025-01-01',NULL,'2025-01-01T12:00:00Z')",
        ]
        for statement in statements:
            with self.subTest(statement=statement):
                before = self.fingerprint()
                self.db.execute(statement)
                self.assertNotEqual(before, self.fingerprint())
        before = self.fingerprint()
        self.db.execute("UPDATE bars SET available_at='2025-03-02T12:00:00Z'")
        self.assertNotEqual(before, self.fingerprint())
        before = self.fingerprint()
        self.db.execute("UPDATE fo_bars SET volume=6")
        self.assertNotEqual(before, self.fingerprint())

    def test_journal_and_import_audit_are_not_market_inputs(self):
        before = self.fingerprint()
        self.db.execute("INSERT INTO journal VALUES ('2025-01-01','ABC','X',1,1,'{}','{}','RISK_ON','x',NULL)")
        self.assertEqual(before, self.fingerprint())
        self.assertNotEqual(before, data_fingerprint(self.db, '2025-01-02', '2025-02-01'))
