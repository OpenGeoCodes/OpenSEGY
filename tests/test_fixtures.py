"""Every fixture must be the file its name says it is.

A fixture set that drifts from its own labels is worse than none: the tests
built on it go on passing while testing something else.
"""
import pytest

from opensegy import scan
from opensegy.fixtures import FIXTURES, materialise

#: fixture name → a finding code its file must produce.
EXPECTED_FINDING = {
    "broken/declares_rev1_carries_rev2": "revision.declared_below_structure",
    "broken/byte_swapped_revision": "revision.byte_swapped",
    "broken/undeclared_extended_headers": "structure.undeclared_extended_textual_headers",
    "broken/trace_count_lies": "structure.trace_count_disagrees",
    "broken/first_trace_offset_lies": "structure.data_start_disagrees",
    "broken/variable_trace_length": "structure.variable_trace_length",
    "broken/truncated_mid_trace": "structure.trailing_bytes",
}


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_every_fixture_can_be_read(name):
    segy = scan(FIXTURES[name]())
    assert segy.revision >= (0, 0)
    assert segy.sample_format is not None


@pytest.mark.parametrize("name", sorted(n for n in FIXTURES if not n.startswith("broken/")))
def test_a_well_formed_fixture_raises_nothing_above_info(name):
    segy = scan(FIXTURES[name]())
    above_info = [f for f in segy.findings if f.severity.value != "info"]
    assert above_info == [], [f.message for f in above_info]


@pytest.mark.parametrize("name,code", sorted(EXPECTED_FINDING.items()))
def test_every_broken_fixture_produces_the_defect_it_is_named_for(name, code):
    segy = scan(FIXTURES[name]())
    assert code in {f.code for f in segy.findings}


def test_the_revision_of_each_fixture_matches_its_folder():
    for name in FIXTURES:
        folder = name.split("/")[0]
        if folder == "broken":
            continue
        expected = {"rev0": (0, 0), "rev1": (1, 0), "rev2": (2, 0), "rev21": (2, 1)}[folder]
        assert scan(FIXTURES[name]()).declared_revision == expected, name


def test_a_layout_stanza_fixture_actually_carries_one():
    segy = scan(FIXTURES["rev21/layout_stanza"]())
    labels = [h.stanza_label for h in segy.extended_textual]
    assert "SEG: Layout 1.0" in labels
    assert "<entry" in segy.extended_textual[0].text


def test_the_fixture_set_writes_to_disk_and_reads_back(tmp_path):
    written = materialise(tmp_path)
    assert len(written) == len(FIXTURES)
    assert all(p.exists() and p.stat().st_size > 3600 for p in written)
    assert scan(str(tmp_path / "rev21" / "layout_stanza.sgy")).revision == (2, 1)


def test_the_cli_inspects_a_file(tmp_path, capsys):
    from opensegy.__main__ import main
    path = tmp_path / "one.sgy"
    path.write_bytes(FIXTURES["rev21/layout_stanza"]())
    assert main(["inspect", str(path)]) == 0
    out = capsys.readouterr().out
    assert "Revision declared  2.1" in out
    assert "SEG: Layout 1.0" in out


def test_the_cli_emits_json(tmp_path, capsys):
    import json
    from opensegy.__main__ import main
    path = tmp_path / "one.sgy"
    path.write_bytes(FIXTURES["rev1/two_extended_textual_headers"]())
    assert main(["inspect", str(path), "--json"]) == 0
    blob = json.loads(capsys.readouterr().out)
    assert blob["data_start"] == 3600 + 2 * 3200
