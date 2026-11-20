"""dev18 Part 0d: the ECMWF member count is never hard-coded in user-facing text. The mirror carries 50 perturbed members and no control member (not 51);
pages read the count from the plume file (`n_members`), and the static pages say "the page shows the actual count"."""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
USER_FACING = list((REPO / "web").glob("*.html")) + list((REPO / "web" / "js").glob("*.js"))


def read(p):
    return p.read_text(encoding="utf-8")


def test_nobody_claims_51_members():
    bad = []
    for p in USER_FACING + list((REPO / "docs").rglob("*.md")) + [REPO / "CLAUDE.md"] + list((REPO / "pipeline").glob("ecmwf.py")):
        for i, line in enumerate(read(p).splitlines(), 1):
            if re.search(r"\b51\b[^.\n]{0,40}(member|ensemble)|(member|ensemble)[^.\n]{0,30}\b51\b", line, re.I) and "not 51" not in line and "no control" not in line.lower():
                bad.append(f"{p.relative_to(REPO)}:{i}")
    assert not bad, f"a 51-member claim (the mirror has 50 perturbed members and no control): {bad}"


def test_pages_do_not_hard_code_the_member_count():
    for p in USER_FACING:
        txt = read(p)
        assert not re.search(r"\b50 (perturbed )?members", txt.replace("at the time of writing the files carry 50 perturbed members", "")), f"{p.name}: hard-coded '50 members'"
        assert "of 50 members" not in txt, p.name


def test_the_plume_view_reads_the_count_and_the_control_flag_from_the_file():
    area = read(REPO / "web" / "js" / "area.js")
    assert "doc.n_members" in area and "doc.control_member" in area
    assert "HRES (single run)" in area and "reference, not a member" in area             # the deterministic line is labelled as such
