"""Unit tests for Extended Tools: HttpFetchTool, ChartTool, PythonSandboxTool, and WeatherTool."""

import json
from unittest.mock import AsyncMock, patch
import httpx
import pytest
from src.infrastructure.tools.chart_tool import ChartTool, build_quickchart_url, render_ascii_bar_chart
from src.infrastructure.tools.http_fetch_tool import HTMLTextExtractor, HttpFetchTool
from src.infrastructure.tools.python_sandbox_tool import PythonSandboxTool
from src.infrastructure.tools.weather_tool import WeatherTool


# ==========================================
# 1. HttpFetchTool Tests
# ==========================================

@pytest.mark.asyncio
async def test_http_fetch_ssrf_blocking():
    """Test that HttpFetchTool strictly blocks private IPs, metadata endpoints, and non-http schemes."""
    tool = HttpFetchTool()

    dangerous_urls = [
        "http://127.0.0.1:8080/admin",
        "http://localhost:3000",
        "http://10.0.0.1/secrets",
        "http://192.168.1.1/router",
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "file:///etc/passwd",
        "ftp://example.com/file",
        "gopher://example.com",
    ]

    for url in dangerous_urls:
        res = await tool.execute({"url": url}, user_id=1)
        assert res.is_error is True, f"Expected {url} to be blocked by SSRF guard"
        assert "SSRF Security Violation" in res.content or "Invalid scheme" in res.content or "Empty or invalid URL" in res.content


@pytest.mark.asyncio
async def test_http_fetch_html_text_extraction(monkeypatch):
    """Test fetching HTML content, stripping tags/scripts, and wrapping untrusted content."""
    tool = HttpFetchTool()

    html_payload = """
    <!DOCTYPE html>
    <html>
    <head><title>Test Page</title><style>body { color: red; }</style></head>
    <body>
        <script>console.log("malicious code");</script>
        <h1>Main Article Heading</h1>
        <p>This is a paragraph with valuable documentation information.</p>
        <div>Nested details about the v2.0 update.</div>
    </body>
    </html>
    """

    mock_response = httpx.Response(
        status_code=200,
        headers={"content-type": "text/html; charset=utf-8"},
        text=html_payload,
        request=httpx.Request("GET", "https://example.com/docs")
    )

    async def mock_get(self, url, **kwargs):
        return mock_response

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    monkeypatch.setattr("src.infrastructure.tools.http_fetch_tool.is_safe_url", lambda url: (True, "URL is safe"))

    res = await tool.execute({"url": "https://example.com/docs"}, user_id=1)
    assert res.is_error is False
    assert "Main Article Heading" in res.content
    assert "valuable documentation information" in res.content
    assert "malicious code" not in res.content
    assert "<script>" not in res.content
    assert "UNTRUSTED EXTERNAL DATA" in res.content


@pytest.mark.asyncio
async def test_http_fetch_json_content(monkeypatch):
    """Test fetching JSON payloads and formatting them nicely."""
    tool = HttpFetchTool()

    json_payload = json.dumps({"status": "healthy", "version": "2.0.0", "active_nodes": 5})
    mock_response = httpx.Response(
        status_code=200,
        headers={"content-type": "application/json"},
        text=json_payload,
        request=httpx.Request("GET", "https://example.com/api/status")
    )

    async def mock_get(self, url, **kwargs):
        return mock_response

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
    monkeypatch.setattr("src.infrastructure.tools.http_fetch_tool.is_safe_url", lambda url: (True, "URL is safe"))

    res = await tool.execute({"url": "https://example.com/api/status"}, user_id=1)
    assert res.is_error is False
    assert "healthy" in res.content
    assert "2.0.0" in res.content


@pytest.mark.asyncio
async def test_http_fetch_timeout_and_error_handling(monkeypatch):
    """Test handling network timeouts and HTTP error responses."""
    tool = HttpFetchTool(timeout=1.0)

    async def mock_timeout(self, url, **kwargs):
        raise httpx.TimeoutException("Connection timed out")

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_timeout)
    monkeypatch.setattr("src.infrastructure.tools.http_fetch_tool.is_safe_url", lambda url: (True, "URL is safe"))

    res = await tool.execute({"url": "https://example.com/slow"}, user_id=1)
    assert res.is_error is True
    assert "timed out" in res.content.lower()


# ==========================================
# 2. ChartTool Tests
# ==========================================

def test_chart_tool_quickchart_url_generation():
    """Test QuickChart.io URL formatting and Chart.js configuration encoding."""
    chart = ChartTool()

    labels = ["Jan", "Feb", "Mar"]
    values = [100.0, 250.0, 400.0]
    title = "Q1 Revenue"

    url = chart.generate_quickchart_url(labels, values, chart_type="bar", title=title)

    assert url.startswith("https://quickchart.io/chart?c=")
    assert "w=500" in url
    assert "h=300" in url

    # Also test standalone build_quickchart_url
    url2 = build_quickchart_url(labels, values, chart_type="line", title="Trend")
    assert "quickchart.io/chart" in url2


def test_chart_tool_ascii_bar_rendering():
    """Test ASCII bar rendering with proportionality, labels, and numeric formatting."""
    chart = ChartTool()

    labels = ["Alpha", "Beta", "Gamma"]
    values = [10.0, 50.0, 100.0]

    ascii_out = chart.render_ascii_bars(labels, values, title="Metrics")

    assert "Alpha" in ascii_out
    assert "Beta" in ascii_out
    assert "Gamma" in ascii_out
    assert "█" in ascii_out
    assert "10" in ascii_out
    assert "100" in ascii_out


@pytest.mark.asyncio
async def test_chart_tool_execution():
    """Test full ChartTool execution returning combined ASCII and URL output."""
    chart = ChartTool()

    args = {
        "chart_type": "pie",
        "title": "Browser Share",
        "labels": ["Chrome", "Firefox", "Safari"],
        "values": [65.0, 20.0, 15.0]
    }

    res = await chart.execute(args, user_id=1)
    assert res.is_error is False
    assert "Visual Chart" in res.content
    assert "quickchart.io/chart" in res.content
    assert "Chrome" in res.content


@pytest.mark.asyncio
async def test_chart_tool_validation_errors():
    """Test input validation for mismatched or non-numeric data."""
    chart = ChartTool()

    # Mismatched lengths
    res1 = await chart.execute({"labels": ["A", "B"], "values": [10.0]}, user_id=1)
    assert res1.is_error is True
    assert "does not match" in res1.content or "Error" in res1.content

    # Non-numeric values
    res2 = await chart.execute({"labels": ["A", "B"], "values": [10.0, "invalid_num"]}, user_id=1)
    assert res2.is_error is True
    assert "must be numbers" in res2.content or "Error" in res2.content


# ==========================================
# 3. PythonSandboxTool Tests
# ==========================================

@pytest.mark.asyncio
async def test_python_sandbox_safe_evaluation():
    """Test safe mathematical, data transformation, and algorithm evaluation."""
    sandbox = PythonSandboxTool()

    # 1. Arithmetic & list comprehension
    code1 = "sum([x**2 for x in range(1, 6)])"
    res1 = await sandbox.execute({"code": code1}, user_id=1)
    assert res1.is_error is False
    assert "55" in res1.content

    # 2. Math module usage
    code2 = "import math\nprint(math.sqrt(144) + math.pow(2, 3))"
    res2 = await sandbox.execute({"code": code2}, user_id=1)
    assert res2.is_error is False
    assert "20.0" in res2.content

    # 3. Statistics module
    code3 = "import statistics\nprint(statistics.mean([10, 20, 30, 40, 50]))"
    res3 = await sandbox.execute({"code": code3}, user_id=1)
    assert res3.is_error is False
    assert "30" in res3.content

    # 4. JSON parsing
    code4 = 'import json\nd = json.loads(\'{"user": "alice", "score": 98}\')\nprint(d["user"], d["score"])'
    res4 = await sandbox.execute({"code": code4}, user_id=1)
    assert res4.is_error is False
    assert "alice 98" in res4.content


@pytest.mark.asyncio
async def test_python_sandbox_infinite_loop_prevention():
    """Test timeout mechanism interrupting infinite loops."""
    sandbox = PythonSandboxTool(timeout=0.3)

    code = "while True:\n    pass"
    res = await sandbox.execute({"code": code}, user_id=1)
    assert res.is_error is True
    assert "Timed Out" in res.content or "timeout" in res.content.lower() or "infinite loop" in res.content


@pytest.mark.asyncio
async def test_python_sandbox_security_blocking():
    """Test blocking forbidden imports, system access, and dunder exploitation."""
    sandbox = PythonSandboxTool()

    malicious_scripts = [
        "import os\nos.system('id')",
        "import sys\nsys.exit(0)",
        "import subprocess\nsubprocess.run(['ls'])",
        "import socket\nsocket.socket()",
        "import shutil\nshutil.rmtree('/tmp')",
        "from os import path",
        "open('/etc/passwd', 'r').read()",
        "eval('2 + 2')",
        "exec('a = 1')",
        "__import__('os').system('ls')",
        "getattr(math, '__class__')",
        "().__{}__.__bases__[0].__subclasses__()".format("class"),
    ]

    for script in malicious_scripts:
        res = await sandbox.execute({"code": script}, user_id=1)
        assert res.is_error is True, f"Expected security violation for: {script}"
        assert "Security Violation" in res.content or "prohibited" in res.content or "prohibited in sandbox" in res.content or "blocked" in res.content.lower()


# ==========================================
# 4. WeatherTool Tests
# ==========================================

def test_weather_tool_query_parsing():
    """Test cleaning city query prefixes."""
    weather = WeatherTool()

    assert weather.parse_city_query("Tokyo") == "Tokyo"
    assert weather.parse_city_query("weather in London") == "London"
    assert weather.parse_city_query("forecast for Jakarta") == "Jakarta"
    assert weather.parse_city_query("  weather for San Francisco  ") == "San Francisco"


@pytest.mark.asyncio
async def test_weather_tool_open_meteo_mock(monkeypatch):
    """Test full weather report retrieval with Open-Meteo API mocks."""
    weather = WeatherTool()

    geo_payload = {
        "results": [{
            "name": "Tokyo",
            "latitude": 35.6895,
            "longitude": 139.6917,
            "country": "Japan",
            "admin1": "Tokyo"
        }]
    }

    forecast_payload = {
        "current": {
            "temperature_2m": 22.5,
            "apparent_temperature": 21.8,
            "relative_humidity_2m": 55,
            "wind_speed_10m": 12.4,
            "weather_code": 0
        }
    }

    async def mock_get(self, url, **kwargs):
        if "geocoding-api" in str(url):
            return httpx.Response(status_code=200, json=geo_payload, request=httpx.Request("GET", str(url)))
        elif "api.open-meteo.com" in str(url):
            return httpx.Response(status_code=200, json=forecast_payload, request=httpx.Request("GET", str(url)))
        return httpx.Response(status_code=404, request=httpx.Request("GET", str(url)))

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    res = await weather.execute({"city": "weather in Tokyo"}, user_id=1)
    assert res.is_error is False
    assert "Tokyo, Japan" in res.content or "Tokyo" in res.content
    assert "22.5°C" in res.content
    assert "Clear sky" in res.content or "☀️" in res.content
    assert "55%" in res.content


@pytest.mark.asyncio
async def test_weather_tool_city_not_found(monkeypatch):
    """Test error handling when geocoding returns no results."""
    weather = WeatherTool()

    geo_payload = {"results": []}

    async def mock_get(self, url, **kwargs):
        return httpx.Response(status_code=200, json=geo_payload, request=httpx.Request("GET", str(url)))

    monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

    res = await weather.execute({"city": "NonExistentCityXYZ"}, user_id=1)
    assert res.is_error is True
    assert "Could not find coordinates" in res.content or "not found" in res.content.lower()
