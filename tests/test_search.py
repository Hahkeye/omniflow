from diary_app.core.search import _tokenize_query, _highlight, _score_text


def test_tokenize_phrases():
    terms = _tokenize_query('budget "next week" plan')
    assert "budget" in terms
    assert "next week" in terms
    assert "plan" in terms


def test_highlight():
    s = _highlight("we reviewed the budget plan carefully", ["budget"])
    assert "**budget**" in s


def test_score():
    assert _score_text("budget budget plan", ["budget"]) > _score_text("plan", ["budget"])
