# Sarissa — DF quick tools: hash, file type, string extractor, timestamp converter.
# © 2026 ShadowStrike. MIT License.
# Aut Viam Inveniam Aut Faciam

import inspect
import io
import re
import zipfile

import pytest
from fastapi.testclient import TestClient

from sarissa.api import tools
from sarissa.api.tools import (
    DEFAULT_MIN_STRINGS,
    compute_hashes,
    convert_timestamp,
    detect_file_type,
    extract_strings,
    set_min_strings,
)
from sarissa.main import create_app

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"


def _zip_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("flag.txt", "flag{zip}")
    return buf.getvalue()


ZIP = _zip_bytes()
ELF = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 8 + b"\x02\x00\x3e\x00" + b"\x00" * 44

ABC = {
    "md5": "900150983cd24fb0d6963f7d28e17f72",
    "sha1": "a9993e364706816aba3e25717850c26c9cd0d89d",
    "sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    "sha512": "ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a"
              "2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f",
}
EMPTY = {
    "md5": "d41d8cd98f00b204e9800998ecf8427e",
    "sha1": "da39a3ee5e6b4b0d3255bfef95601890afd80709",
    "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "sha512": "cf83e1357eefb8bdf1542850d66d8007d620e4050b5715dc83f4a921d36ce9ce"
              "47d0d13c5d85f2b0ff8318d2877eec2f63b931bd47417a81a538327af927da3e",
}


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(sessions_dir=tmp_path)) as c:
        yield c


@pytest.fixture(autouse=True)
def reset_min_strings():
    yield
    set_min_strings(DEFAULT_MIN_STRINGS)


# --- hash calculator --------------------------------------------------------

def test_hashes_known_vectors():
    assert compute_hashes(b"abc") == ABC
    assert compute_hashes(b"") == EMPTY


def test_hashes_always_all_four():
    assert set(compute_hashes(b"x")) == {"md5", "sha1", "sha256", "sha512"}


def test_hash_endpoint_returns_all_four(client):
    r = client.post("/api/tools/hash", content=b"abc")
    assert r.status_code == 200
    body = r.json()
    assert {k: body[k] for k in ABC} == ABC
    assert body["size"] == 3


def test_hash_endpoint_empty_body(client):
    body = client.post("/api/tools/hash", content=b"").json()
    assert {k: body[k] for k in EMPTY} == EMPTY
    assert body["size"] == 0


def test_hash_endpoint_large_body(client):
    data = bytes(range(256)) * 8192  # 2 MiB, arrives in multiple chunks
    body = client.post("/api/tools/hash", content=data).json()
    assert {k: body[k] for k in ABC} == compute_hashes(data)


# --- file type inspector (magic bytes only) -----------------------------------

@pytest.mark.parametrize(
    "data,mime",
    [(PNG, "image/png"), (PDF, "application/pdf"), (ZIP, "application/zip"), (b"hello world\n", "text/plain")],
)
def test_detect_by_magic(data, mime):
    assert detect_file_type(data)["mime"] == mime


def test_detect_elf():
    assert "ELF" in detect_file_type(ELF)["description"]


def test_detect_takes_no_filename():
    assert list(inspect.signature(detect_file_type).parameters) == ["data"]


def test_magic_hex_and_size():
    r = detect_file_type(PNG)
    assert r["magic_hex"].startswith("89 50 4e 47")
    assert r["size"] == len(PNG)


def test_filetype_endpoint_ignores_names(client):
    # A "name" in the query string or headers must make no difference.
    r = client.post(
        "/api/tools/filetype?filename=notes.txt",
        content=PNG,
        headers={"Content-Disposition": 'attachment; filename="notes.txt"'},
    )
    assert r.json()["mime"] == "image/png"
    r = client.post("/api/tools/filetype?filename=photo.png", content=b"just some text\n")
    assert r.json()["mime"] == "text/plain"


# --- string extractor -------------------------------------------------------

def values(result):
    return [s["value"] for s in result["strings"]]


def test_default_min_length_is_4():
    assert DEFAULT_MIN_STRINGS == 4
    assert tools.get_min_strings() == 4


def test_min_length_filter_default():
    data = b"\x00abc\x00abcd\x01xyzzy\xff"
    assert values(extract_strings(data)) == ["abcd", "xyzzy"]


def test_min_length_cli_override():
    set_min_strings(6)
    data = b"abcde\x00abcdef\x00"
    assert values(extract_strings(data)) == ["abcdef"]


def test_min_length_must_be_positive():
    with pytest.raises(ValueError):
        set_min_strings(0)


def test_offsets_and_utf16():
    data = b"\x00\x00flag{ascii}\x00\xff" + "wide1".encode("utf-16-le")
    result = extract_strings(data)
    assert result["strings"][0] == {"offset": 2, "encoding": "ascii", "value": "flag{ascii}"}
    assert {"offset": 15, "encoding": "utf-16le", "value": "wide1"} in result["strings"]


def test_truncation():
    data = b"\x00".join([b"word"] * 10)
    result = extract_strings(data, limit=3)
    assert result["count"] == 10 and result["truncated"] is True
    assert len(result["strings"]) == 3


def test_strings_endpoint_ignores_min_length_param(client):
    data = b"ab\x00abc\x00abcd\x00"
    r = client.post("/api/tools/strings?min_length=2&min_strings=2", content=data)
    assert values(r.json()) == ["abcd"]
    assert "min_length" not in r.json()


def test_strings_endpoint_follows_cli_setting(client):
    set_min_strings(5)
    r = client.post("/api/tools/strings", content=b"abcd\x00abcde\x00")
    assert values(r.json()) == ["abcde"]


def test_ui_has_no_min_length_control(client):
    html = client.get("/").text
    assert re.search(r"min.?(length|strings)", html, re.I) is None


def test_ui_makes_no_external_calls(client):
    html = client.get("/").text
    # The only URL allowed is Treska on loopback (Phase 7 Parse tab) — never an external host.
    urls = set(re.findall(r"https?://[^\s\"'`<>)]*", html))
    assert urls == {"http://localhost:7332"}


def test_swagger_docs_disabled(client):
    # Swagger UI loads assets from a CDN — must stay off.
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404


# --- timestamp converter ----------------------------------------------------

def test_unix_zero_all_formats():
    r = convert_timestamp("0", "unix")
    assert r["iso"] == "1970-01-01T00:00:00Z"
    assert r["unix"] == 0 and r["unix_ms"] == 0
    assert r["filetime"] == 116444736000000000
    assert r["webkit"] == 11644473600000000
    assert r["cocoa"] == -978307200
    assert r["hfs"] == 2082844800


@pytest.mark.parametrize(
    "value,fmt,iso",
    [
        ("116444736000000000", "filetime", "1970-01-01T00:00:00Z"),
        ("1700000000000", "unix_ms", "2023-11-14T22:13:20Z"),
        ("13000000000000000", "webkit", "2012-12-14T23:06:40Z"),
        ("0", "cocoa", "2001-01-01T00:00:00Z"),
        ("0", "hfs", "1904-01-01T00:00:00Z"),
        ("1.5", "unix", "1970-01-01T00:00:01.500000Z"),
        ("2023-11-14T22:13:20Z", "iso", "2023-11-14T22:13:20Z"),
        ("2023-11-14 22:13:20", "iso", "2023-11-14T22:13:20Z"),
    ],
)
def test_conversions(value, fmt, iso):
    assert convert_timestamp(value, fmt)["iso"] == iso


def test_iso_to_unix_roundtrip():
    r = convert_timestamp("2023-11-14T22:13:20+00:00", "iso")
    assert r["unix"] == 1700000000
    assert convert_timestamp(str(r["filetime"]), "filetime")["unix"] == 1700000000


@pytest.mark.parametrize("value,fmt", [("abc", "unix"), ("nan", "unix"), ("99999999999999999", "unix"), ("not-a-date", "iso")])
def test_invalid_timestamps(value, fmt):
    with pytest.raises(ValueError):
        convert_timestamp(value, fmt)


def test_timestamp_endpoint(client):
    r = client.post("/api/tools/timestamp", json={"value": "0", "format": "unix"})
    assert r.status_code == 200 and r.json()["iso"] == "1970-01-01T00:00:00Z"
    assert client.post("/api/tools/timestamp", json={"value": "abc", "format": "unix"}).status_code == 422
    assert client.post("/api/tools/timestamp", json={"value": "0", "format": "bogus"}).status_code == 422


# --- mutation sweep (J01) ---------------------------------------------------

def test_magic_hex_is_first_16_bytes():
    assert detect_file_type(PNG)["magic_hex"] == PNG[:16].hex(" ")


def test_min_strings_accepts_one():
    set_min_strings(1)
    assert tools.get_min_strings() == 1
    with pytest.raises(ValueError) as exc:
        set_min_strings(0)
    assert str(exc.value) == "--min-strings must be at least 1"


def test_explicit_min_length_overrides_default():
    data = b"abcd\x00abcdefgh"
    assert len(extract_strings(data)["strings"]) == 2
    assert values(extract_strings(data, min_length=8)) == ["abcdefgh"]


def test_truncation_boundary():
    r = extract_strings(b"aaaa\x00bbbb", limit=2)
    assert (r["count"], r["truncated"], len(r["strings"])) == (2, False, 2)


def test_iso_fractional_seconds():
    assert convert_timestamp("1970-01-01T00:00:01.250000Z", "iso")["unix"] == 1.25


@pytest.mark.parametrize("fmt,iso", [("cocoa", "2001-01-01T00:00:01Z"), ("hfs", "1904-01-01T00:00:01Z")])
def test_epoch_formats_nonzero(fmt, iso):
    assert convert_timestamp("1", fmt)["iso"] == iso


@pytest.mark.parametrize(
    "value,fmt,message",
    [
        ("abc", "unix", "Not a number: 'abc'"),
        ("nan", "unix", "Not a finite number: 'nan'"),
        ("0", "bogus", "Unknown format 'bogus'"),
        ("99999999999999999", "unix", "Timestamp out of range (years 1-9999)"),
    ],
)
def test_timestamp_error_messages(value, fmt, message):
    with pytest.raises(ValueError) as exc:
        convert_timestamp(value, fmt)
    assert str(exc.value) == message


def test_timestamp_number_types_and_human():
    zero = convert_timestamp("0")  # default format is unix
    assert zero == convert_timestamp("0", "unix")
    assert type(zero["unix"]) is int
    assert zero["human"] == "Thu 01 Jan 1970 00:00:00 UTC"
    half = convert_timestamp("1.5", "unix")
    assert half["unix"] == 1.5
    assert half["unix_ms"] == 1500 and type(half["unix_ms"]) is int


# --- main() CLI wiring (uvicorn, browser timer and console are faked) -------

@pytest.fixture
def launch(monkeypatch):
    import types

    import sarissa.main

    calls = types.SimpleNamespace(run=None, timer=None, daemon=None, printed=[])

    class FakeTimer:
        def __init__(self, interval, function, args=None):
            calls.timer = (interval, function, args)
            self.daemon = False

        def start(self):
            calls.daemon = self.daemon

    class FakeConsole:
        def print(self, *args, **kwargs):
            calls.printed.append(args)

    def fake_run(*args, **kwargs):
        calls.run = (args, kwargs)

    monkeypatch.setattr(sarissa.main, "threading", types.SimpleNamespace(Timer=FakeTimer))
    monkeypatch.setattr(sarissa.main, "uvicorn", types.SimpleNamespace(run=fake_run))
    monkeypatch.setattr(sarissa.main, "Console", FakeConsole)
    return calls


def test_main_serves_on_port_7331_loopback(launch):
    import webbrowser

    from fastapi import FastAPI

    import sarissa.main

    set_min_strings(9)
    sarissa.main.main([])
    assert tools.get_min_strings() == DEFAULT_MIN_STRINGS
    (args, kwargs) = launch.run
    assert len(args) == 1 and isinstance(args[0], FastAPI)
    assert kwargs == {"host": "127.0.0.1", "port": 7331, "log_level": "warning"}
    assert launch.timer == (1.0, webbrowser.open, ("http://127.0.0.1:7331",))
    assert launch.daemon is True
    assert len(launch.printed) == 3


def test_main_min_strings_passthrough(launch):
    import sarissa.main

    sarissa.main.main(["--min-strings", "6"])
    assert tools.get_min_strings() == 6


def test_main_rejects_min_strings_below_one(launch, capsys):
    import sarissa.main

    with pytest.raises(SystemExit) as exc:
        sarissa.main.main(["--min-strings", "0"])
    assert exc.value.code == 2
    assert "--min-strings must be at least 1" in capsys.readouterr().err
    assert launch.run is None
