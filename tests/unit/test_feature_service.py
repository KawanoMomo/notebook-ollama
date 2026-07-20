import pytest

from core.exceptions import AppError
from core.feature_service import FeatureService


def test_default_off_and_optin_roundtrip(tmp_path):
    svc = FeatureService(tmp_path)
    assert svc.is_enabled("table-figure-rag") is False
    svc.set_optin("table-figure-rag", True)
    assert svc.is_enabled("table-figure-rag") is True
    # 別インスタンスでも永続化されている
    assert FeatureService(tmp_path).is_enabled("table-figure-rag") is True


def test_set_optin_unknown_flag_raises(tmp_path):
    with pytest.raises(AppError):
        FeatureService(tmp_path).set_optin("no-such-flag", True)


def test_list_flags_shape(tmp_path):
    rows = FeatureService(tmp_path).list_flags()
    row = next(r for r in rows if r["id"] == "table-figure-rag")
    assert row["stage"] == "beta"
    assert row["enabled"] is False
    assert row["name"]


def test_stale_optin_for_removed_flag_is_ignored(tmp_path):
    from core import settings_store
    settings_store.save_section(tmp_path, "beta_optins", {"removed-flag": True})
    svc = FeatureService(tmp_path)
    assert svc.is_enabled("removed-flag") is False
    assert all(r["id"] != "removed-flag" for r in svc.list_flags())
