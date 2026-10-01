from company_people.normalize import (
    canonical_linkedin_company,
    canonical_linkedin_profile,
    csv_safe,
    normalize_input_website,
    website_key,
)


def test_profile_canonicalization_strips_trk_and_keeps_host():
    parsed = canonical_linkedin_profile(
        "https://www.linkedin.com/in/avery-stone-example-co?trk=org-employees"
    )
    assert parsed is not None
    assert parsed.url == "https://www.linkedin.com/in/avery-stone-example-co"
    assert parsed.slug == "avery-stone-example-co"
    assert "trk=org-employees" in parsed.raw


def test_profile_accepts_localized_host():
    parsed = canonical_linkedin_profile("https://co.linkedin.com/in/casey-north/")
    assert parsed is not None
    assert parsed.url == "https://co.linkedin.com/in/casey-north"
    assert parsed.host == "co.linkedin.com"


def test_profile_rejects_non_profile_paths_and_hosts():
    assert canonical_linkedin_profile("https://www.linkedin.com/company/dedicated-developers/") is None
    assert canonical_linkedin_profile("https://www.linkedin.com/in/") is None
    assert canonical_linkedin_profile("https://linkedin.com.evil.com/in/john/") is None
    assert canonical_linkedin_profile("https://notlinkedin.com/in/john/") is None
    assert canonical_linkedin_profile("https://www.linkedin.com/posts/john/") is None
    assert canonical_linkedin_profile("ftp://www.linkedin.com/in/john/") is None


def test_company_url():
    parsed = canonical_linkedin_company("https://www.linkedin.com/company/dedicated-developers/")
    assert parsed is not None
    assert parsed.url == "https://www.linkedin.com/company/dedicated-developers"
    assert canonical_linkedin_company("https://www.linkedin.com/in/john/") is None


def test_apex_host_equals_www():
    # linkedin.com без поддомена = www.linkedin.com (одна страница, не два кандидата)
    a = canonical_linkedin_company("https://linkedin.com/company/bland-ai")
    b = canonical_linkedin_company("https://www.linkedin.com/company/bland-ai/")
    assert a is not None and b is not None
    assert a.url == b.url == "https://www.linkedin.com/company/bland-ai"
    p = canonical_linkedin_profile("https://linkedin.com/in/john-doe")
    assert p is not None and p.url == "https://www.linkedin.com/in/john-doe"


def test_website_key_normalizes_www_and_scheme():
    assert website_key("https://www.dedicateddevelopers.com/") == "dedicateddevelopers.com"
    assert website_key("dedicateddevelopers.com") == "dedicateddevelopers.com"
    assert normalize_input_website("dedicateddevelopers.com") == "https://dedicateddevelopers.com/"
    assert website_key("http://user:pass@example.com/") is None
    assert normalize_input_website("https://example.com:8080/") is None


def test_csv_formula_neutralization():
    assert csv_safe("=SUM(A1:A5)").startswith("'")
    assert csv_safe("+4915").startswith("'")
    assert csv_safe("@cmd").startswith("'")
    assert csv_safe("-2024-01-01").startswith("'")
    assert csv_safe("Anna-Marie Müller") == "Anna-Marie Müller"
