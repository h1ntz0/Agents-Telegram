"""Integration tests for System Doctor diagnostics."""

import os
import pytest
from src.application.doctor import SystemDoctor


@pytest.mark.asyncio
async def test_doctor_on_missing_env(tmp_path):
    missing_env = str(tmp_path / "non_existent.env")
    doctor = SystemDoctor(env_path=missing_env)

    passed, results = await doctor.run_diagnostics()
    assert passed is False
    assert any(r["name"] == "Configuration File" and r["status"] == "FAIL" for r in results)


@pytest.mark.asyncio
async def test_doctor_python_version():
    doctor = SystemDoctor(env_path=".env")
    passed, results = await doctor.run_diagnostics()
    py_check = next((r for r in results if r["name"] == "Python Runtime"), None)
    assert py_check is not None
    assert py_check["status"] == "PASS"
