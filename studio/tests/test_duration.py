import unittest

from studio.duration import parse_duration


class DurationTest(unittest.TestCase):
    def test_parse_duration_seconds(self) -> None:
        self.assertEqual(parse_duration("45s"), 45)

    def test_parse_duration_minutes(self) -> None:
        self.assertEqual(parse_duration("30m"), 1800)

    def test_parse_duration_hours(self) -> None:
        self.assertEqual(parse_duration("100h"), 360000)

    def test_parse_duration_rejects_invalid(self) -> None:
        with self.assertRaises(ValueError):
            parse_duration("30x")


if __name__ == "__main__":
    unittest.main()
