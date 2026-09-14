"""Unit tests for the read-only P9 readiness report contract."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("baby_readiness", ROOT / "scripts" / "check_baby_readiness.py")
assert SPEC and SPEC.loader
readiness = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = readiness
SPEC.loader.exec_module(readiness)


def test_missing_database_is_explicit_failure_without_secret(monkeypatch):
    secret_dsn = "postgresql://operator:very-secret@db.example/internal"
    monkeypatch.setenv("DATABASE_URL", secret_dsn)
    report = readiness.collect_readiness(dsn=None, corpus="synthetic", provider="unconfigured")
    assert report["status"] == "failed"
    assert "database_url_not_configured" in str(report)
    assert secret_dsn not in str(report)


def test_unconfigured_provider_is_blocked_not_silently_replaced(monkeypatch):
    monkeypatch.delenv("BABY_SEARCH_PROVIDER", raising=False)
    result = readiness._provider_check("auto", "synthetic")
    assert result.status == "blocked"
    assert result.reason == "search_provider_unconfigured"


def test_local_file_provider_check_does_not_create_index_directory(monkeypatch, tmp_path):
    absent = tmp_path / "does-not-exist"
    monkeypatch.setenv("BABY_SEARCH_PROVIDER", "local-file")
    monkeypatch.setenv("BABY_SEARCH_STORAGE_ROOT", str(absent))
    result = readiness._provider_check("local-file", "synthetic")
    assert result.status == "pass"
    assert result.observed["index_present"] is False
    assert not absent.exists()


def test_rule_coverage_skips_explicit_clothing_data_gap():
    slots = readiness._expected_slots()
    assert "의류" not in slots
    assert {"stroller", "car_seat"} <= set(slots["외출"])
