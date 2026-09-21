import pytest

from cookistash.mealie.transformer import _format_time, _parse_times


class TestFormatTime:
    def test_no_comment(self):
        assert _format_time({"quantity": {"value": 600}, "comment": ""}) == "10 mins"

    def test_with_comment(self):
        result = _format_time({"quantity": {"value": 60}, "comment": "resting"})
        assert result == "1 mins resting"

    def test_missing_comment_key(self):
        assert _format_time({"quantity": {"value": 120}}) == "2 mins"


class TestParseTimes:
    def test_parses_both_times(self):
        times = [
            {"type": "activeTime", "comment": "", "quantity": {"value": 600}},
            {"type": "totalTime", "comment": "", "quantity": {"value": 36000}},
        ]
        total, prep = _parse_times(times)
        assert total == "600 mins"
        assert prep == "10 mins"

    def test_raises_on_missing_type(self):
        with pytest.raises(TypeError):
            _parse_times([{"type": "activeTime", "comment": "", "quantity": {"value": 60}}])
