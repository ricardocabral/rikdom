from datetime import timezone, timedelta
import unittest

from rikdom.import_normalization import parse_decimal, normalize_datetime


class ExplicitNormalizationTests(unittest.TestCase):
    def test_separator_conventions_control_ambiguous_number(self):
        self.assertEqual(parse_decimal("1,234", decimal_separator=".", grouping_separator=","), 1234)
        self.assertEqual(parse_decimal("1,234", decimal_separator=",", grouping_separator="."), 1.234)

    def test_core_does_not_strip_currency_symbols(self):
        for raw in ("$1.25", "R$1.25", "1,23.45", "NaN", "Infinity", True):
            self.assertIsNone(parse_decimal(raw, decimal_separator=".", grouping_separator=","))

    def test_invalid_grouping_is_not_reinterpreted(self):
        self.assertIsNone(parse_decimal("1.234,56", decimal_separator=".", grouping_separator=","))

    def test_date_order_and_timezone_are_explicit(self):
        self.assertEqual(normalize_datetime("03/04/2026", date_formats=("%m/%d/%Y",), naive_timezone=timezone.utc), "2026-03-04T00:00:00Z")
        self.assertEqual(normalize_datetime("03/04/2026", date_formats=("%d/%m/%Y",), naive_timezone=timezone(timedelta(hours=-3))), "2026-04-03T03:00:00Z")
        self.assertIsNone(normalize_datetime("03/04/2026", naive_timezone=timezone.utc))
        self.assertIsNone(normalize_datetime("2026-04-03", naive_timezone=None))
        self.assertEqual(normalize_datetime("2026-04-03T10:00:00+02:00", naive_timezone=None), "2026-04-03T08:00:00Z")
