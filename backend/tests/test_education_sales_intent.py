from northstar_api.services.education_sales_intent import detects_education_sales_intent


def test_detects_clear_education_purchase_intent() -> None:
    positives = [
        "What is the price of the CPA course?",
        "How much does the CMA program cost?",
        "Do you offer a payment plan for the ACCA course?",
        "I want to enroll in the CPA course.",
        "Can I upgrade my course plan?",
    ]
    for message in positives:
        assert detects_education_sales_intent(message), message


def test_does_not_treat_academic_price_questions_as_sales_intent() -> None:
    negatives = [
        "Explain price elasticity of demand.",
        "What is historical cost accounting?",
        "How are course grades calculated?",
        "Explain the purchase method in accounting.",
        "Tell me about the CPA syllabus.",
        "",
    ]
    for message in negatives:
        assert not detects_education_sales_intent(message), message
