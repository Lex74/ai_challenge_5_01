import unittest

from review_pr import analyze_review_for_critical_issues


class TestAnalyzeReviewForCriticalIssues(unittest.TestCase):
    def test_empty_review_text(self):
        try:
            result = analyze_review_for_critical_issues("")
        except Exception as exc:
            self.fail(f"Unexpected exception: {exc}")
        self.assertFalse(result["has_critical_issues"])
        self.assertFalse(result["has_issues"])
        self.assertEqual(result["critical_count"], 0)

    def test_none_review_text(self):
        try:
            result = analyze_review_for_critical_issues(None)
        except Exception as exc:
            self.fail(f"Unexpected exception: {exc}")
        self.assertFalse(result["has_critical_issues"])
        self.assertFalse(result["has_issues"])
        self.assertEqual(result["critical_count"], 0)

    def test_non_string_review_text(self):
        try:
            result = analyze_review_for_critical_issues({"text": "критическая проблема"})
        except Exception as exc:
            self.fail(f"Unexpected exception: {exc}")
        self.assertFalse(result["has_critical_issues"])
        self.assertFalse(result["has_issues"])

    def test_whitespace_only_review_text(self):
        try:
            result = analyze_review_for_critical_issues("   \n\t  ")
        except Exception as exc:
            self.fail(f"Unexpected exception: {exc}")
        self.assertFalse(result["has_critical_issues"])
        self.assertFalse(result["has_issues"])
        self.assertEqual(result["critical_count"], 0)

    def test_special_symbols_review_text(self):
        try:
            result = analyze_review_for_critical_issues("### $$$ @@@ !!!")
        except Exception as exc:
            self.fail(f"Unexpected exception: {exc}")
        self.assertFalse(result["has_critical_issues"])
        self.assertFalse(result["has_issues"])

    def test_detects_critical_section(self):
        review_text = (
            "## ⚠️ Критические проблемы\n"
            "- Необработанный None в функции foo\n"
            "- Уязвимость в обработке входных данных\n"
            "\n## ✅ Положительные моменты\n"
            "Все остальное хорошо.\n"
        )
        result = analyze_review_for_critical_issues(review_text)
        self.assertTrue(result["has_critical_issues"])
        self.assertTrue(result["has_issues"])
        self.assertEqual(result["critical_count"], 2)

    def test_detects_general_issues(self):
        review_text = (
            "## 💡 Предложения по улучшению\n"
            "- Улучшить читаемость\n"
            "\n## 📝 Мелкие замечания\n"
            "- Небольшие стилистические правки\n"
        )
        result = analyze_review_for_critical_issues(review_text)
        self.assertFalse(result["has_critical_issues"])
        self.assertTrue(result["has_issues"])

    def test_detects_critical_keywords(self):
        review_text = "Найдена критическая проблема: возможен crash при пустом вводе."
        result = analyze_review_for_critical_issues(review_text)
        self.assertTrue(result["has_critical_issues"])
        self.assertTrue(result["has_issues"])


if __name__ == "__main__":
    unittest.main()
