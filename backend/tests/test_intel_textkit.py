import pytest

from app.intel.bayes import BM25, NaiveBayes
from app.intel.textkit import (approx_find, art_ratio, deep_normalize, flat, invisible_count, jaro_winkler, levenshtein,
                               mixed_script_words, spaced_letters, tokens, zalgo)


def test_levenshtein_and_early_exit():
    assert levenshtein("kitten", "sitting") == 3
    assert levenshtein("", "abc") == 3
    assert levenshtein("same", "same") == 0
    assert levenshtein("abcdefgh", "zzzzzzzz", max_dist=2) == 3


def test_jaro_winkler():
    assert jaro_winkler("savah", "savah") == 1.0
    assert jaro_winkler("savah", "savahh") > 0.95
    assert jaro_winkler("savah", "zzzzz") < 0.5


def test_approx_find_substring_with_typos():
    assert approx_find("frerobux", "iwantfrerobusnow", 1) == 1
    assert approx_find("frerobux", "iwantfrerobuxnow", 1) == 0
    assert approx_find("frerobux", "nothingsimilarhere", 1) is None


def test_deep_normalize_defeats_disguises():
    assert deep_normalize("Fr33   R0bux") == deep_normalize("free robux")
    assert deep_normalize("\u1d00\u1d04\u1d04") == deep_normalize("acc")
    assert "k" in deep_normalize("|<")
    assert deep_normalize("zero\u200bwidth") == deep_normalize("zerowidth")
    assert flat("f r e e e   r o b u x") == flat("free robux")


def test_text_trick_detectors():
    assert mixed_script_words("hello fr\u0435e") == ["fr\u0435e"]   # Cyrillic е inside a Latin word
    assert mixed_script_words("hello world") == []
    assert mixed_script_words("\u043f\u0440\u0438\u0432\u0435\u0442") == []  # a fully Russian word is fine
    marks, letters = zalgo("h\u0300\u0301\u0302\u0303e\u0300\u0301\u0302\u0303y")
    assert marks >= 8 and letters == 3
    assert invisible_count("a\u200bb\u200bc\u200b") == 3
    assert art_ratio("\u2588\u2588\u2588\u2588\u2593\u2593\u2593\u2593\u2592\u2592\u2592\u2592") == 1.0
    assert art_ratio("just words") == 0.0
    assert spaced_letters("f r e e r o b u x now") == 9 and spaced_letters("a normal sentence") == 1


def test_tokens_generalise_numbers_urls_mentions():
    assert tokens("send 0.5 btc to @bob at https://x.example/y") == tokens("send 7 btc to @alice at https://other.example/z")


def _trained():
    nb = NaiveBayes()
    for t in ["free robux click link", "double your bitcoin now", "win free giftcards here", "claim your prize now", "free vbucks link",
              "send btc get double", "join my telegram for profit", "guaranteed profit dm me"]:
        nb.train(t, "spam")
    for t in ["gg nice play", "what game is this", "hello everyone", "that boss is tough", "the music is great", "lol nice one",
              "i love this stream", "can you play fifa next"]:
        nb.train(t, "ham")
    return nb


def test_naive_bayes_separates_and_explains():
    nb = _trained()
    p_spam, words = nb.predict("free bitcoin link now")
    p_ham, _ = nb.predict("nice play the music is great")
    assert p_spam > 0.9 and p_ham < 0.1 and words
    assert nb.predict("zzzz qqqq")[0] == 0.5   # nothing known: no opinion


def test_naive_bayes_untrained_has_no_opinion_and_rejects_bad_label():
    nb = NaiveBayes()
    assert nb.predict("free money")[0] == 0.5
    with pytest.raises(ValueError):
        nb.train("x", "maybe")


def test_naive_bayes_roundtrip():
    nb = _trained()
    again = NaiveBayes.load(nb.dump())
    assert again.docs == nb.docs
    assert abs(again.predict("free bitcoin link now")[0] - nb.predict("free bitcoin link now")[0]) < 1e-9


def test_bm25_ranks_the_closest_document_first():
    bm = BM25().build([(1, "free robux click the link"), (2, "hello everyone how are you"), (3, "double your bitcoin today")])
    top = bm.search("click link for robux", top=3)
    assert top[0][1] == 1
    assert bm.search("zzz nothing") == []
    assert BM25().search("anything") == []
