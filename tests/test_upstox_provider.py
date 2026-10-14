import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from stockex.market.schema import open_market_db
from stockex.market.queries import load_history
from stockex.market.health import market_health
from stockex.signals.scan import scan
from stockex.providers.upstox import (
    Instrument, ProviderError, UpstoxClient, parse_candles, sync_upstox, validate_instruments,
)


EQUITY = {"type": "equity", "symbol": "EXAMPLE", "isin": "INE848E01016", "instrument_key": "NSE_EQ|INE848E01016", "series": "EQ"}
INDEX = {"type": "index", "index_name": "NIFTY 50", "instrument_key": "NSE_INDEX|Nifty 50"}
START, END = "2026-09-21", "2026-09-22"
NOW = datetime(2026, 9, 23, 10, tzinfo=timezone.utc)


def payload(close=103, day=START):
    return json.dumps({"status": "success", "data": {"candles": [
        [day + "T00:00:00+05:30", 100, 105, 99, close, 50000, 0]
    ]}}).encode()


def client(*responses):
    transport = Mock(side_effect=responses or [(200, payload(), {})])
    return UpstoxClient("private-token", transport=transport, sleeper=Mock(), clock=lambda: NOW)


class UpstoxProviderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.connection = open_market_db(self.root / "market.sqlite3")
        self.manifest = {"schema_version": 1, "instruments": [EQUITY, INDEX]}

    def tearDown(self):
        self.connection.close()
        self.temporary.cleanup()

    def test_wire_request_is_get_candles_with_encoded_identity_and_bearer(self):
        instance = client()
        result = instance.daily(validate_instruments(self.manifest)[0], START, END)
        args = instance._transport.call_args.args
        self.assertEqual(args[0], "https://api.upstox.com/v3/historical-candle/NSE_EQ%7CINE848E01016/days/1/2026-09-22/2026-09-21")
        self.assertEqual(args[1]["Authorization"], "Bearer private-token")
        self.assertEqual(result["retrieved_at"], "2026-09-23T10:00:00Z")
        self.assertEqual(result["candles"][0]["date"], START)

    def test_bad_token_headers_fail_without_echo_or_request(self):
        transport = Mock()
        for token in ("private-token\n", "private-token\r\nInjected: x", " private-token"):
            with self.assertRaises(ProviderError) as caught:
                UpstoxClient(token, transport=transport)
            self.assertNotIn("private-token", str(caught.exception))
        transport.assert_not_called()

    def test_sync_keeps_missing_fields_null_and_availability_is_retrieval(self):
        result = sync_upstox(self.connection, self.manifest, START, END, self.root / "raw",
                             client=client((200, payload(), {}), (200, payload(), {})))
        row = self.connection.execute("SELECT * FROM bars").fetchone()
        self.assertIsNone(row["traded_value"])
        self.assertIsNone(row["delivery_pct"])
        self.assertIsNone(row["delivery_qty"])
        self.assertIsNone(row["prev_close"])
        self.assertEqual(row["available_at"], "2026-09-23T10:00:00Z")
        self.assertEqual(len(load_history(self.connection, "EXAMPLE", END)), 0)
        self.assertEqual(result["availability_policy"], "RETRIEVED_AT")
        audit = self.connection.execute("SELECT * FROM provider_downloads").fetchall()
        self.assertEqual(len(audit), 2)
        self.assertTrue(all(Path(item["raw_path"]).is_file() for item in audit))
        self.assertNotIn("private-token", repr([tuple(item) for item in audit]))

    def test_repeat_sync_keeps_first_availability_and_records_new_retrieval(self):
        manifest = {"schema_version": 1, "instruments": [EQUITY]}
        for _ in range(2):
            result = sync_upstox(self.connection, manifest, START, END, self.root / "raw", client=client())
        self.assertEqual(result["instruments"][0]["inserted"], 0)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM bars").fetchone()[0], 1)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM provider_downloads").fetchone()[0], 2)

    def test_delayed_data_requires_explicit_knowledge_cutoff_and_unverified_basis_blocks_strict_health(self):
        sync_upstox(self.connection, self.manifest, START, END, self.root / "raw",
                    client=client((200, payload(), {}), (200, payload(), {})))
        self.assertEqual(scan(self.connection, START)["universe"]["traded_on_date"], 0)
        report = scan(self.connection, START, known_at="2026-09-23T10:00:00Z")
        self.assertEqual(report["universe"]["traded_on_date"], 1)
        health = market_health(self.connection, START, min_history=1, known_at="2026-09-23T10:00:00Z")
        codes = {item["code"] for item in health["issues"]}
        self.assertNotIn("SESSION_MISSING", codes)
        self.assertIn("PROVIDER_PRICE_BASIS_UNVERIFIED", codes)
        with self.assertRaises(ValueError):
            scan(self.connection, START, known_at="2026-09-21T12:00:00Z")

    def test_later_response_conflict_rolls_back_the_whole_provider_batch(self):
        initial = {"schema_version": 1, "instruments": [EQUITY]}
        sync_upstox(self.connection, initial, START, END, self.root / "raw", client=client())
        manifest = {"schema_version": 1, "instruments": [INDEX, EQUITY]}
        with self.assertRaisesRegex(ProviderError, "conflicts"):
            sync_upstox(self.connection, manifest, START, END, self.root / "raw",
                        client=client((200, payload(), {}), (200, payload(close=104), {})))
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM index_bars").fetchone()[0], 0)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM provider_downloads").fetchone()[0], 1)

    def test_failed_fetch_publishes_no_market_rows(self):
        with self.assertRaises(ProviderError):
            sync_upstox(self.connection, self.manifest, START, END, self.root / "raw",
                        client=client((200, payload(), {}), (401, b"private-token", {})))
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM bars").fetchone()[0], 0)

    def test_retry_honors_bounded_retry_after_and_does_not_echo_error_body(self):
        instance = client((429, b"", {"Retry-After": "1000"}), (200, payload(), {}))
        instance.daily(validate_instruments(self.manifest)[0], START, END)
        instance._sleeper.assert_called_once_with(5.0)
        with self.assertRaises(ProviderError) as caught:
            client((401, b"private-token", {})).daily(validate_instruments(self.manifest)[0], START, END)
        self.assertNotIn("private-token", str(caught.exception))

    def test_unbounded_or_duplicate_identity_rejected_before_network(self):
        for instrument in ({**EQUITY, "isin": "INE000000000"},
                           {**EQUITY, "symbol": "bad\nheader"},
                           {**INDEX, "instrument_key": "BSE_INDEX|Sensex"}):
            with self.assertRaises(ValueError):
                validate_instruments({"schema_version": 1, "instruments": [instrument]})
        with self.assertRaises(ValueError):
            validate_instruments({"schema_version": 1, "instruments": [EQUITY, EQUITY]})

    def test_malformed_root_and_bad_candle_numbers_fail_closed(self):
        for raw in (b"[]", b"null", b"{}", b"not json", payload(close=200), payload(close=float("nan"))):
            with self.subTest(raw=raw), self.assertRaises(ProviderError):
                parse_candles(raw, START, END)

    def test_quantities_outside_csv_exact_integer_range_are_rejected(self):
        decoded = json.loads(payload())
        decoded["data"]["candles"][0][5] = 9007199254740993
        with self.assertRaises(ProviderError):
            parse_candles(json.dumps(decoded).encode(), START, END)

    def test_current_day_candle_not_accepted_as_closed_session(self):
        with self.assertRaises(ProviderError) as caught:
            client((200, payload(day="2026-09-23"), {})).daily(
                Instrument(EQUITY["instrument_key"], "equity", "EXAMPLE", EQUITY["isin"]),
                "2026-09-23", "2026-09-23")
        self.assertEqual(caught.exception.code, "PROVIDER_SESSION_INCOMPLETE")

    def test_corrupt_cached_raw_response_never_gets_trusted(self):
        import hashlib
        raw_dir = self.root / "raw"
        raw_dir.mkdir()
        (raw_dir / (hashlib.sha256(payload()).hexdigest() + ".json")).write_text("corrupt")
        with self.assertRaises(ProviderError) as caught:
            sync_upstox(self.connection, {"schema_version": 1, "instruments": [EQUITY]},
                        START, END, raw_dir, client=client())
        self.assertEqual(caught.exception.code, "PROVIDER_CACHE_CORRUPT")
