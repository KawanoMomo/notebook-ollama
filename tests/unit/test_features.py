from core.features import REGISTRY, get_flag, is_enabled


def test_registry_contains_table_figure_rag():
    flag = get_flag("table-figure-rag")
    assert flag is not None
    assert flag.stage == "beta"


def test_is_enabled_beta_requires_optin():
    assert is_enabled("table-figure-rag", {}) is False
    assert is_enabled("table-figure-rag", {"table-figure-rag": False}) is False
    assert is_enabled("table-figure-rag", {"table-figure-rag": True}) is True


def test_is_enabled_unknown_flag_is_false():
    assert is_enabled("no-such-flag", {"no-such-flag": True}) is False


def test_is_enabled_ga_ignores_optin(monkeypatch):
    import core.features as feats
    ga = feats.FeatureFlag(
        id="ga-sample", name="GA", description="", stage="ga",
        since="2026-01-01", spec="",
    )
    monkeypatch.setattr(feats, "REGISTRY", (*feats.REGISTRY, ga))
    assert is_enabled("ga-sample", {}) is True
    assert is_enabled("ga-sample", {"ga-sample": False}) is True
