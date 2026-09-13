from __future__ import annotations

from procmine.process_discovery.document_identity import document_key


def test_word_dash_compatibility_mode_suffix():
    assert document_key("Microsoft Word", "keiyaku_kaijo_tetsuzuki  -  Compatibility Mode - Word") == "keiyaku_kaijo_tetsuzuki"


def test_word_bracket_compatibility_mode_suffix():
    assert document_key("Microsoft Word", "keiyaku_kaijo_tetsuzuki [Compatibility Mode] - Word") == "keiyaku_kaijo_tetsuzuki"


def test_both_suffix_formats_give_the_same_key_for_the_same_document():
    a = document_key("Microsoft Word", "gyomu_itaku_kyuuyo_kitei  -  Compatibility Mode - Word")
    b = document_key("Microsoft Word", "gyomu_itaku_kyuuyo_kitei [Compatibility Mode] - Word")
    assert a == b == "gyomu_itaku_kyuuyo_kitei"


def test_word_transient_resume_reading_is_none():
    assert document_key("Microsoft Word", "Resume Reading") is None


def test_excel_strips_suffix():
    assert document_key("Microsoft Excel", "expense_calc - Excel") == "expense_calc"
    assert document_key("Microsoft Excel", "budget_analysis - Excel") == "budget_analysis"


def test_excel_transient_opening_is_none():
    assert document_key("Microsoft Excel", "Opening - Excel") is None


def test_non_office_application_is_none():
    assert document_key("Microsoft Edge", "HR人事給与システム - Profile 1 - Microsoft​ Edge") is None


def test_notepad_strips_unsaved_marker_and_suffix():
    assert document_key("Notepad", "*精算確認メモ - Notepad") == "精算確認メモ"


def test_notepad_untitled_or_bare_is_none():
    assert document_key("Notepad", "Untitled - Notepad") is None
    assert document_key("Notepad", "Notepad") is None


def test_missing_title_is_none():
    assert document_key("Microsoft Word", None) is None
    assert document_key("Microsoft Word", "") is None
