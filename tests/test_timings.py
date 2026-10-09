"""Line-breaking, width accounting and words.json validation."""

import json

import pytest

from subreel.timings import (
    TimingsError,
    Word,
    char_units,
    line_units,
    load_words,
    parse_words_data,
    split_lines,
)


# ---------------------------------------------------------------------------
# width
# ---------------------------------------------------------------------------


def test_char_units_cjk_is_one_ascii_is_half():
    assert char_units("你") == 1.0
    assert char_units("a") == 0.5
    assert char_units("ab") == 1.0
    assert char_units("你好") == 2.0


def test_line_units_counts_joining_spaces():
    ws = [Word("ab", 0, 1), Word("cd", 1, 2)]
    # "ab cd" = 5 half-width chars = 2.5 units (4 letters + 1 space)
    assert line_units(ws) == 2.5


# ---------------------------------------------------------------------------
# line breaking
# ---------------------------------------------------------------------------


def _words(text, step=0.2):
    """One Word per character, contiguous timings."""
    out = []
    t = 0.0
    for ch in text:
        out.append(Word(ch, t, t + step))
        t += step
    return out


def test_chinese_long_sentence_wraps_by_max_chars():
    words = _words("这是一个没有任何标点的很长的中文句子需要按字符宽度自动换行显示")
    lines = split_lines(words, max_chars=10)
    assert len(lines) > 1
    for line in lines[:-1]:  # the final line may be short
        assert line_units(line.words) <= 10


def test_break_prefers_punctuation():
    # 8 CJK chars then a comma: the comma should stay at the end of a line and
    # the line should not overshoot the budget by much.
    words = _words("今天天气不错，我们出去走走吧")
    lines = split_lines(words, max_chars=7)
    first = lines[0].text
    assert first.endswith("，")
    # nothing after the comma should be on the first line
    assert "我" not in first


def test_english_wraps_on_spaces():
    en = "the quick brown fox jumps over the lazy dog".split()
    words = [Word(w, i * 0.3, i * 0.3 + 0.28) for i, w in enumerate(en)]
    lines = split_lines(words, max_chars=10)
    for line in lines:
        # each rendered line stays within the budget
        assert line_units(line.words) <= 10
        # breaks land on word boundaries, never mid-word
        for tok in line.text.split():
            assert tok in en


def test_punctuation_is_not_orphaned():
    # A comma that would otherwise start a new line is pulled back.
    words = _words("石石石石石石石石，")
    lines = split_lines(words, max_chars=8)
    assert all(not ln.text.startswith("，") for ln in lines)
    # and every word is preserved exactly once, in order
    joined = "".join(w.text for ln in lines for w in ln.words)
    assert joined == "石石石石石石石石，"


def test_sentence_end_closes_a_line_eagerly():
    words = _words("你好。世界。")
    lines = split_lines(words, max_chars=22)
    assert [ln.text for ln in lines] == ["你好。", "世界。"]


def test_hold_is_applied():
    words = [Word("你好", 0.0, 0.5), Word("世界", 3.0, 3.5)]
    lines = split_lines(words, hold=0.3)
    assert len(lines) == 1
    assert lines[0].end == pytest.approx(3.8)


def test_hold_skipped_when_it_would_overlap_next_line():
    words = [Word("甲", 0.0, 0.5), Word("乙", 0.6, 1.0)]
    lines = split_lines(words, max_chars=1, hold=0.3)
    assert len(lines) == 2
    # 0.5 + 0.3 = 0.8 > 0.6 (next start), so the hold is dropped
    assert lines[0].end == pytest.approx(0.5)


def test_line_timing_spans_first_to_last_word():
    words = [Word("一", 0.2, 0.5), Word("二", 0.5, 0.9)]
    lines = split_lines(words, hold=0.0)
    assert lines[0].start == pytest.approx(0.2)
    assert lines[0].end == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# words.json validation
# ---------------------------------------------------------------------------


def _write(tmp_path, doc):
    path = tmp_path / "w.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return str(path)


def test_load_valid_words(tmp_path):
    doc = {
        "language": "zh",
        "source": "edge-tts",
        "words": [
            {"text": "你", "start": 0.12, "end": 0.31},
            {"text": "好", "start": 0.31, "end": 0.58},
        ],
    }
    data = load_words(_write(tmp_path, doc))
    assert data.language == "zh"
    assert data.source == "edge-tts"
    assert [w.text for w in data.words] == ["你", "好"]


def test_empty_words_rejected(tmp_path):
    with pytest.raises(TimingsError, match="must not be empty"):
        load_words(_write(tmp_path, {"words": []}))


def test_start_not_before_end_rejected(tmp_path):
    with pytest.raises(TimingsError, match="strictly less"):
        load_words(_write(tmp_path, {"words": [{"text": "x", "start": 1.0, "end": 1.0}]}))


def test_out_of_order_rejected(tmp_path):
    doc = {
        "words": [
            {"text": "a", "start": 1.0, "end": 1.5},
            {"text": "b", "start": 0.5, "end": 0.9},
        ]
    }
    with pytest.raises(TimingsError, match="non-decreasing"):
        load_words(_write(tmp_path, doc))


def test_missing_field_rejected(tmp_path):
    with pytest.raises(TimingsError, match="missing required field 'end'"):
        load_words(_write(tmp_path, {"words": [{"text": "x", "start": 0.0}]}))


def test_wrong_type_rejected(tmp_path):
    with pytest.raises(TimingsError, match="must be a number"):
        load_words(_write(tmp_path, {"words": [{"text": "x", "start": "0", "end": 1.0}]}))


def test_missing_words_key_rejected(tmp_path):
    with pytest.raises(TimingsError, match="missing required key 'words'"):
        load_words(_write(tmp_path, {"language": "zh"}))


def test_bad_json_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(TimingsError, match="not valid JSON"):
        load_words(str(path))


def test_equal_starts_allowed():
    data = parse_words_data(
        {
            "words": [
                {"text": "a", "start": 0.0, "end": 0.5},
                {"text": "b", "start": 0.5, "end": 0.8},
                {"text": "c", "start": 0.5, "end": 0.9},
            ]
        }
    )
    assert len(data.words) == 3


def test_roundtrip_dump(tmp_path):
    data = parse_words_data({"language": "en", "source": "x", "words": [
        {"text": "hi", "start": 0.0, "end": 0.4}]})
    out = tmp_path / "out.json"
    data.dump(str(out))
    again = load_words(str(out))
    assert again.language == "en"
    assert again.words[0].text == "hi"