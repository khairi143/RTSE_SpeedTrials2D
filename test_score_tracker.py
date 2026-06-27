import os
import tempfile
import unittest
from unittest.mock import patch

from score_tracker import (
    parse_score,
    format_table,
    next_run_number,
    load_scores,
    save_scores,
)


class TestParseScore(unittest.TestCase):
    def test_parses_integer_string(self):
        self.assertEqual(parse_score("10"), 10.0)

    def test_parses_decimal_string(self):
        self.assertEqual(parse_score("12.5"), 12.5)

    def test_rejects_non_numeric_string(self):
        with self.assertRaises(ValueError):
            parse_score("abc")


class TestFormatTable(unittest.TestCase):
    def test_empty_rows_returns_placeholder(self):
        self.assertEqual(format_table([]), "(no runs recorded yet)")

    def test_nonempty_rows_includes_run_and_score(self):
        table = format_table([(1, 10.0), (2, 8.5)])
        self.assertIn("1", table)
        self.assertIn("10.0", table)
        self.assertIn("2", table)
        self.assertIn("8.5", table)


class TestNextRunNumber(unittest.TestCase):
    def test_empty_rows_starts_at_one(self):
        self.assertEqual(next_run_number([]), 1)

    def test_nonempty_rows_increments_from_max(self):
        self.assertEqual(next_run_number([(1, 5.0), (3, 7.0)]), 4)


class TestLoadSaveScores(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        os.remove(self.path)  # start with a non-existent file

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)

    def test_load_missing_file_returns_empty_list(self):
        self.assertEqual(load_scores(self.path), [])

    def test_save_then_load_round_trips(self):
        rows = [(1, 10.0), (2, 7.5)]
        save_scores(rows, self.path)
        self.assertEqual(load_scores(self.path), rows)

    def test_load_corrupt_file_returns_empty_list(self):
        with open(self.path, "w") as f:
            f.write("not,a,valid,csv\nheader\n1,2,3,4\n")
        self.assertEqual(load_scores(self.path), [])


class TestMainLoop(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        os.remove(self.path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)

    def test_full_session_saves_scores_and_quits(self):
        from score_tracker import main

        inputs = iter(["10", "7.5", "q"])
        with patch("builtins.input", lambda _: next(inputs)):
            main(self.path)

        self.assertEqual(load_scores(self.path), [(1, 10.0), (2, 7.5)])

    def test_invalid_input_does_not_advance_run_number(self):
        from score_tracker import main

        inputs = iter(["abc", "5", "q"])
        with patch("builtins.input", lambda _: next(inputs)):
            main(self.path)

        self.assertEqual(load_scores(self.path), [(1, 5.0)])


if __name__ == "__main__":
    unittest.main()
