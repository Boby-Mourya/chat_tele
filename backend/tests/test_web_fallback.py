from northstar_api.services.web_fallback import _lite_results


def test_lite_results_unwraps_search_links_and_keeps_snippets() -> None:
    html = """
    <table>
      <tr><td>1.</td><td><a class="result-link"
        href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.imaglobal.org%2Fcertifications%2Fcma&amp;rut=x">
        CMA Certification | IMA</a></td></tr>
      <tr><td></td><td>The CMA is a management accounting certification provided by IMA.</td></tr>
    </table>
    """

    assert _lite_results(html) == [
        (
            "CMA Certification | IMA",
            "https://www.imaglobal.org/certifications/cma",
            "The CMA is a management accounting certification provided by IMA.",
        )
    ]
