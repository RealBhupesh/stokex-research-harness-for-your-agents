"""Regression checks for causal reference data and immutable market imports."""
from datetime import date
from pathlib import Path
import sqlite3
import tempfile
import unittest

import market_fixtures as fx
from stockex.market.corporate import adjustment_events
from stockex.market.importers import MarketImportError, import_market_file
from stockex.market.queries import load_history, restrictions_on
from stockex.market.schema import open_market_db


class MarketVintageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = open_market_db(self.root / 'market.sqlite3')
        self.addCleanup(self.db.close)

    def test_late_action_and_restriction_do_not_change_earlier_knowledge(self):
        for day, price in ((date(2026, 9, 1), 100), (date(2026, 9, 2), 50)):
            path = self.root / f'cash-{day}.csv'
            fx.write_cm_full(path, [fx.cm_full_line('ABC', day, price, price, price, price, 100, 1000)])
            import_market_file(self.db, path)
        action = self.root / 'actions.csv'
        fx.write_corp_actions(action, [('ABC', 'Bonus 1:1', date(2026, 9, 2))])
        import_market_file(self.db, action, available_at='2026-09-03T12:00:00Z')
        self.assertEqual(load_history(self.db, 'ABC', '2026-09-02').close, [100, 50])
        self.assertEqual(load_history(self.db, 'ABC', '2026-09-03').close, [50, 50])
        restrictions = self.root / 'restrictions.csv'
        restrictions.write_text('list,symbol,stage,from_date,to_date\nASM,ABC,1,2026-09-02,\n')
        import_market_file(self.db, restrictions, available_at='2026-09-03T12:00:00Z')
        self.assertEqual(restrictions_on(self.db, '2026-09-01', through='2026-09-05'), {})
        self.assertEqual(restrictions_on(self.db, '2026-09-02'), {})
        self.assertEqual(restrictions_on(self.db, '2026-09-03'), {'ABC': ['ASM:1']})

    def test_missing_session_does_not_become_inferred_action(self):
        series = fx.make_series([(100, 100, 100, 100, 1000, 40), (120, 120, 120, 120, 1000, 40)])
        series.dates = ['2026-09-01', '2026-09-03']
        series.prev_close[1] = 110
        self.assertEqual(adjustment_events(series, []), [])

    def test_market_revisions_fail_atomically(self):
        day, expiry = date(2026, 9, 1), date(2026, 9, 29)
        original, revised = self.root / 'fo.csv', self.root / 'fo-revised.csv'
        fx.write_udiff(original, [fx.udiff_line(day, 'FO', 'STF', 'ABC', expiry=expiry, c=100, oi=1000)])
        fx.write_udiff(revised, [fx.udiff_line(day, 'FO', 'STF', 'ABC', expiry=expiry, c=100, oi=2000)])
        import_market_file(self.db, original)
        with self.assertRaisesRegex(MarketImportError, 'Conflicting fo_bars'):
            import_market_file(self.db, revised)
        self.assertEqual(self.db.execute('SELECT open_interest FROM fo_bars').fetchone()[0], 1000)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM market_import_runs').fetchone()[0], 1)

    def test_delivery_correction_cannot_rewrite_history(self):
        day = date(2026, 9, 1)
        for index, delivery in enumerate((40, 90)):
            path = self.root / f'cash-{index}.csv'
            fx.write_cm_full(path, [fx.cm_full_line('ABC', day, 100, 100, 100, 100, 100, 1000, delivery)])
            if index == 0:
                import_market_file(self.db, path)
            else:
                with self.assertRaisesRegex(MarketImportError, 'Conflicting bar delivery'):
                    import_market_file(self.db, path)
        self.assertEqual(load_history(self.db, 'ABC', day.isoformat()).delivery_pct, [40])

    def test_legacy_reference_rows_migrate_with_conservative_availability(self):
        path = self.root / 'legacy.sqlite3'
        with sqlite3.connect(path) as connection:
            connection.execute('CREATE TABLE corporate_actions(symbol TEXT, ex_date TEXT, kind TEXT, factor REAL, purpose TEXT, PRIMARY KEY(symbol,ex_date,kind))')
            connection.execute("INSERT INTO corporate_actions VALUES('ABC','2020-01-01','BONUS',0.5,'Bonus 1:1')")
            connection.execute('CREATE TABLE restrictions(list_name TEXT,symbol TEXT,stage TEXT,from_date TEXT,to_date TEXT,PRIMARY KEY(list_name,symbol,from_date))')
            connection.execute("INSERT INTO restrictions VALUES('ASM','ABC','1','2020-01-01',NULL)")
        migrated = open_market_db(path)
        self.addCleanup(migrated.close)
        self.assertEqual(restrictions_on(migrated, '2020-01-02'), {})
        row = migrated.execute('SELECT available_at FROM corporate_actions').fetchone()
        self.assertGreater(row[0], '2020-01-02T13:00:00Z')
