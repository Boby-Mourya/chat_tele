from northstar_api.services.web_fallback import selected_web_fallback


def test_saved_fallback_policy_is_used_and_invalid_values_fail_closed() -> None:
    assert selected_web_fallback({"webFallback": "off"}) == "off"
    assert selected_web_fallback({"webFallback": "related_only"}) == "related_only"
    assert selected_web_fallback({"webFallback": "public"}) == "public"
    assert selected_web_fallback({"webFallback": "anything_else"}) == "off"
    assert selected_web_fallback(None) == "off"
