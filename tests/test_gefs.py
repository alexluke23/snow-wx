"""NOAA GEFS plume (pipeline/gefs.py, dev18 stretch 5, built OFF): grid index, wgrib2 .idx parsing, window selection, per-member accumulation, snow estimate, gating, missing members,
published / not-yet-released exits. Offline: a fake mirror, no eccodes."""
import json
from datetime import datetime, timezone

import numpy as np
import pytest

from pipeline import ecmwf as E
from pipeline import gefs as G

CYC = datetime(2026, 11, 18, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def fast_fetch(monkeypatch, tmp_path):
    monkeypatch.setitem(G.DEFAULTS, "min_interval_s", 0.0)
    monkeypatch.setitem(G.DEFAULTS, "backoff_s", 0.001)
    monkeypatch.setattr(G, "REPO_ROOT", tmp_path / "repo")          # dev21: the resume cache must never be written into the REAL data_cache by a test


PTS = [{"id": "alta", "lat": 40.57, "lon": -111.63, "elev_ft": 10556}]
IDX_TEXT = """1:0:d=2026111800:VIS:surface:24 hour fcst:ENS=+1
18:{a}:d=2026111800:APCP:surface:{w}-{e} hour acc fcst:ENS=+1
19:{c}:d=2026111800:CSNOW:surface:{w}-{e} hour ave fcst:ENS=+1
20:{z}:d=2026111800:PRMSL:mean sea level:{e} hour fcst:ENS=+1
"""


class Resp:
    def __init__(self, text="", content=b"", status=200):
        self.text, self.content, self.status_code = text, content, status


class Mirror:
    def __init__(self, missing_members=0, released=True):
        self.headers, self.gets, self.missing = {}, [], missing_members
        self.released = released

    def head(self, u, **k):
        return Resp(status=200 if self.released else 404)

    def get(self, u, headers=None, timeout=None, **k):
        self.gets.append((u, (headers or {}).get("Range")))
        member = u.split("/")[-1].split(".")[0]
        if member in G.MEMBERS[len(G.MEMBERS) - self.missing:]:
            return Resp(status=404)
        step = int(u.split(".f")[-1].split(".")[0])
        if u.endswith(".idx"):
            return Resp(text=IDX_TEXT.format(a=1000, c=2000, z=3000, w=step - 6, e=step))
        return Resp(content=(b"A" if (headers or {}).get("Range", "").startswith("bytes=1000") else b"C") * 10, status=206)      # APCP at offset 1000, CSNOW at 2000


def fake_decode(monkeypatch):
    def decode(blob):
        return np.full((721, 1440), 2.0 if blob[:1] == b"A" else 0.5, dtype="float32")        # APCP: 2 mm per bucket; CSNOW: 0.5 frozen share
    monkeypatch.setattr(E, "decode", decode)
    monkeypatch.setattr(E.time, "sleep", lambda s: None)


def test_grid_index_starts_at_0e_and_wraps():
    assert G.grid_index(40.57, -111.63) == (198, 993)                 # -111.63 mod 360 = 248.37 deg east of 0 E -> column 993 (ECMWF's grid starts at 180 E: 273)
    assert G.grid_index(10.0, 0.0)[1] == 0 and G.grid_index(10.0, 359.9)[1] == 0 and G.grid_index(10.0, -0.2)[1] == 1439
    assert G.grid_index(95, 10)[0] == 0 and G.grid_index(-95, 10)[0] == 720


def test_parse_idx_windows_and_byte_ranges():
    rows = G.parse_idx(IDX_TEXT.format(a=1000, c=2000, z=3000, w=6, e=12) + "garbage line\n21:4000:d=2026111800:TMP:2 m above ground:12 hour fcst:ENS=+1\n")
    byparam = {r["param"]: r for r in rows}
    assert set(byparam) == {"APCP", "CSNOW"}                          # only windowed (acc / ave) messages are kept
    ap = G.pick(rows, "APCP", 12, 6)
    assert ap and (ap["start"], ap["end"], ap["offset"], ap["length"]) == (6, 12, 1000, 1000) and G.byte_range(ap) == "bytes=1000-1999"
    assert G.pick(rows, "APCP", 12, 3) is None and G.pick(rows, "APCP", 18, 6) is None and G.pick(rows, "CSNOW", 12, 6)["kind"] == "ave"
    last = G.parse_idx("5:10:d=2026111800:APCP:surface:0-6 hour acc fcst:ENS=+1\n")[0]
    assert last["length"] is None and G.byte_range(last) == "bytes=10-"


def test_url_layout_and_member_list():
    c = G.configure(None)
    assert G.url(c, CYC, "gep01", 24, ".idx") == "https://noaa-gefs-pds.s3.amazonaws.com/gefs.20261118/00/atmos/pgrb2sp25/gep01.t00z.pgrb2s.0p25.f024.idx"
    assert len(G.MEMBERS) == 31 and G.MEMBERS[0] == "gec00" and G.MEMBERS[-1] == "gep30" and c["enabled"] is False and G.steps_for(c)[:3] == [0, 6, 12]


def run(tmp_path, monkeypatch, mirror, **kw):
    fake_decode(monkeypatch)
    tmp_path.mkdir(parents=True, exist_ok=True)
    gh = tmp_path / "gh.txt"
    return G.run({"gefs": {"enabled": True, "max_step_h": 12, "workers": 2}}, mirror, tmp_path / "models", cycle=CYC, points=PTS, github_output=str(gh), **kw), gh


def test_run_accumulates_each_members_own_buckets_and_estimates_snow(tmp_path, monkeypatch):
    res, gh = run(tmp_path, monkeypatch, Mirror())
    assert res["ok"] and res["n_members"] == 31 and res["control_member"] is True and res["areas"] == 1 and res["missing_member_messages"] == 0
    d = json.loads((tmp_path / "models" / "gefs" / "plume" / "alta.json").read_text(encoding="utf-8"))
    assert d["model"] == "NOAA GEFS" and d["hours"] == [0, 6, 12] and d["n_members"] == 31 and d["control_member"] is True and "hres_tp" not in d
    assert d["tp"][0] == [0] * 31 and d["tp"][1][0] == 20 and d["tp"][2][0] == 40 and len(d["tp"][2]) == 31         # 2 mm per bucket = 20 tenths of mm; summed per member over time
    assert d["sf"][1][5] == 10 and d["sf"][2][5] == 20                                                                # half of each bucket frozen (CSNOW 0.5)
    idx = json.loads((tmp_path / "models" / "gefs" / "index.json").read_text(encoding="utf-8"))
    assert idx["n_members"] == 31 and "public domain" in idx["attribution"] and idx["bytes_downloaded"] > 0 and "new=true" in gh.read_text(encoding="utf-8")
    ranges = [r for _, r in Mirror().gets]
    assert ranges == []                                                                                                 # (a fresh mirror: nothing leaked between tests)


def test_one_byte_range_get_per_message_and_no_whole_file_download(tmp_path, monkeypatch):
    m = Mirror()
    run(tmp_path, monkeypatch, m)
    grib = [(u, r) for u, r in m.gets if not u.endswith(".idx")]
    assert len(grib) == 31 * 2 * 2 and all(r and r.startswith("bytes=") for _, r in grib)                              # members x (APCP, CSNOW) x two steps


def test_missing_members_up_to_the_limit_are_tolerated_and_more_fail_the_run(tmp_path, monkeypatch):
    res, _ = run(tmp_path, monkeypatch, Mirror(missing_members=3))
    d = json.loads((tmp_path / "models" / "gefs" / "plume" / "alta.json").read_text(encoding="utf-8"))
    assert res["missing_member_messages"] == 6 and d["tp"][2][30] is None and d["tp"][2][0] is not None
    # dev21: more than 20 % missing is NOT an error: the run stops (new=false, exit 0) and the retry attempt resumes from the cached steps
    monkeypatch.setattr(G, "REPO_ROOT", tmp_path / "repo2")             # a fresh cache (the run above cached its steps)
    res, gh = run(tmp_path / "x", monkeypatch, Mirror(missing_members=7))                                             # 7 of 31 > 20 %
    assert res["skipped"] == "incomplete" and "new=false" in gh.read_text(encoding="utf-8") and not (tmp_path / "x" / "models" / "gefs").exists()


def test_the_retry_attempt_resumes_from_the_step_cache(tmp_path, monkeypatch):
    first, _ = run(tmp_path / "a", monkeypatch, Mirror())
    m = Mirror()
    again, gh = run(tmp_path / "b", monkeypatch, m)                       # same cycle, same points: every step comes from data_cache/gefs/<cycle>
    assert again["fetch"]["cache_hits"] == 2 and not [g for g in m.gets if g[1]] and "new=true" in gh.read_text(encoding="utf-8")
    a = json.loads((tmp_path / "a" / "models" / "gefs" / "plume" / "alta.json").read_text(encoding="utf-8"))
    b = json.loads((tmp_path / "b" / "models" / "gefs" / "plume" / "alta.json").read_text(encoding="utf-8"))
    assert a["tp"] == b["tp"] and a["sf"] == b["sf"]
    assert (tmp_path / "repo" / "data_cache" / "gefs" / "2026111800" / "step_006.npz").exists()


def test_flag_off_published_and_not_released_never_download(tmp_path, monkeypatch):
    from pipeline.version import stamp
    m = Mirror()
    assert G.run({}, m, tmp_path, points=PTS) == {"ok": False, "skipped": "disabled"} and m.gets == []
    fake_decode(monkeypatch)
    gh = tmp_path / "gh.txt"
    res = G.run({"gefs": {"enabled": True}}, m, tmp_path / "o", cycle=CYC, points=PTS, published=stamp("2026111800", "gefs"), github_output=str(gh))
    assert res["skipped"] == "published" and "new=false" in gh.read_text(encoding="utf-8") and m.gets == []
    res = G.run({"gefs": {"enabled": True}}, Mirror(released=False), tmp_path / "o2", now=datetime(2026, 11, 18, 3, tzinfo=timezone.utc), points=PTS, github_output=str(gh))
    assert res["skipped"] == "not-released" and not (tmp_path / "o2").exists()


def test_newest_cycle_needs_the_last_step_of_the_control_and_the_last_member():
    c = G.configure(None)
    now = datetime(2026, 11, 18, 20, 30, tzinfo=timezone.utc)
    assert G.newest_cycle(Mirror(), c, now) == datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
    assert G.newest_cycle(Mirror(released=False), c, now) is None
    assert G.newest_cycle(Mirror(), c, datetime(2026, 11, 18, 14, tzinfo=timezone.utc)) == CYC                        # 12Z is only 2 h old: take 00Z


def test_config_default_is_off_and_the_cli_does_nothing_without_force(tmp_path):
    from pipeline.__main__ import main
    from pipeline.common import load_config
    assert load_config()["gefs"]["enabled"] is False
    gh = tmp_path / "gh.txt"
    assert main(["gefs", "--out", str(tmp_path / "o"), "--github-output", str(gh)]) == 0 and "new=false" in gh.read_text(encoding="utf-8") and not (tmp_path / "o").exists()
