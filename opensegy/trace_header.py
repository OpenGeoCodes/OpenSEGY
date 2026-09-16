"""The 240-byte trace header, and the extensions rev 2 allows after it.

The architectural point of this module is the one the standard forces and most
readers ignore:

    240 bytes is the *first* trace header, not the whole of it.

Rev 2 permits additional 240-byte headers per trace, each ending with an 8-byte
name at bytes 233-240 that says what it is. So a trace header is modelled as a
list of blocks, and a field can be addressed in any of them. A reader that
hard-codes a 240-byte limit cannot see a vendor extension even when the file
declares one, which is why `parse` takes the blocks it is given rather than one
buffer.

Positions here are relative to the block, so byte 1 is the first byte of that
trace header. The absolute file position lands on each Reading.
"""
from __future__ import annotations

from .fields import FieldDef, HeaderView, Reading
from .types import Endian

TRACE_HEADER_SIZE = 240

_REV0: tuple[FieldDef, ...] = (
    FieldDef("trace_sequence_line",       1, "int32", "Trace sequence number within line"),
    FieldDef("trace_sequence_file",       5, "int32", "Trace sequence number within file"),
    FieldDef("field_record",              9, "int32", "Original field record number (FFID)"),
    FieldDef("trace_number_field",       13, "int32", "Trace number within the field record"),
    FieldDef("energy_source_point",      17, "int32", "Energy source point number"),
    FieldDef("ensemble",                 21, "int32", "Ensemble number (CDP/CMP)"),
    FieldDef("trace_number_ensemble",    25, "int32", "Trace number within the ensemble"),
    FieldDef("trace_id",                 29, "int16", "Trace identification code"),
    FieldDef("vertically_summed",        31, "int16", "Vertically summed traces"),
    FieldDef("horizontally_stacked",     33, "int16", "Horizontally stacked traces"),
    FieldDef("data_use",                 35, "int16", "Data use (1 production, 2 test)"),
    FieldDef("offset",                   37, "int32", "Distance from source point to receiver group"),
    FieldDef("receiver_elevation",       41, "int32", "Receiver group elevation"),
    FieldDef("source_elevation",         45, "int32", "Surface elevation at source"),
    FieldDef("source_depth",             49, "int32", "Source depth below surface"),
    FieldDef("receiver_datum_elevation", 53, "int32", "Datum elevation at receiver group"),
    FieldDef("source_datum_elevation",   57, "int32", "Datum elevation at source"),
    FieldDef("source_water_depth",       61, "int32", "Water depth at source"),
    FieldDef("receiver_water_depth",     65, "int32", "Water depth at group"),
    FieldDef("elevation_scalar",         69, "int16", "Scalar for elevations and depths"),
    FieldDef("coordinate_scalar",        71, "int16", "Scalar for coordinates"),
    FieldDef("source_x",                 73, "int32", "Source X coordinate"),
    FieldDef("source_y",                 77, "int32", "Source Y coordinate"),
    FieldDef("group_x",                  81, "int32", "Group X coordinate"),
    FieldDef("group_y",                  85, "int32", "Group Y coordinate"),
    FieldDef("coordinate_unit",          89, "int16", "Coordinate units"),
    FieldDef("weathering_velocity",      91, "int16", "Weathering velocity"),
    FieldDef("subweathering_velocity",   93, "int16", "Subweathering velocity"),
    FieldDef("source_uphole_time",       95, "int16", "Uphole time at source (ms)"),
    FieldDef("group_uphole_time",        97, "int16", "Uphole time at group (ms)"),
    FieldDef("source_static",            99, "int16", "Source static correction (ms)"),
    FieldDef("receiver_static",         101, "int16", "Group static correction (ms)"),
    FieldDef("total_static",            103, "int16", "Total static applied (ms)"),
    FieldDef("lag_time_a",              105, "int16", "Lag time A (ms)"),
    FieldDef("lag_time_b",              107, "int16", "Lag time B (ms)"),
    FieldDef("delay_recording_time",    109, "int16", "Delay recording time (ms)"),
    FieldDef("mute_time_start",         111, "int16", "Mute time start (ms)"),
    FieldDef("mute_time_end",           113, "int16", "Mute time end (ms)"),
    FieldDef("samples_per_trace",       115, "int16", "Number of samples in this trace"),
    FieldDef("sample_interval",         117, "int16", "Sample interval for this trace"),
    FieldDef("gain_type",               119, "int16", "Gain type of field instruments"),
    FieldDef("instrument_gain",         121, "int16", "Instrument gain constant"),
    FieldDef("instrument_initial_gain", 123, "int16", "Instrument early gain"),
    FieldDef("correlated",              125, "int16", "Correlated (1 no, 2 yes)"),
    FieldDef("sweep_frequency_start",   127, "int16", "Sweep frequency at start"),
    FieldDef("sweep_frequency_end",     129, "int16", "Sweep frequency at end"),
    FieldDef("sweep_length",            131, "int16", "Sweep length (ms)"),
    FieldDef("sweep_type",              133, "int16", "Sweep type"),
    FieldDef("sweep_taper_start",       135, "int16", "Sweep trace taper length at start"),
    FieldDef("sweep_taper_end",         137, "int16", "Sweep trace taper length at end"),
    FieldDef("taper_type",              139, "int16", "Taper type"),
    FieldDef("alias_filter_frequency",  141, "int16", "Alias filter frequency"),
    FieldDef("alias_filter_slope",      143, "int16", "Alias filter slope"),
    FieldDef("notch_filter_frequency",  145, "int16", "Notch filter frequency"),
    FieldDef("notch_filter_slope",      147, "int16", "Notch filter slope"),
    FieldDef("low_cut_frequency",       149, "int16", "Low cut frequency"),
    FieldDef("high_cut_frequency",      151, "int16", "High cut frequency"),
    FieldDef("low_cut_slope",           153, "int16", "Low cut slope"),
    FieldDef("high_cut_slope",          155, "int16", "High cut slope"),
    FieldDef("year",                    157, "int16", "Year data recorded"),
    FieldDef("day_of_year",             159, "int16", "Day of year"),
    FieldDef("hour",                    161, "int16", "Hour of day"),
    FieldDef("minute",                  163, "int16", "Minute of hour"),
    FieldDef("second",                  165, "int16", "Second of minute"),
    FieldDef("time_basis",              167, "int16", "Time basis code"),
    FieldDef("trace_weighting",         169, "int16", "Trace weighting factor"),
    FieldDef("group_number_roll_switch", 171, "int16", "Geophone group number, roll switch"),
    FieldDef("group_number_first",      173, "int16", "Geophone group number, first trace"),
    FieldDef("group_number_last",       175, "int16", "Geophone group number, last trace"),
    FieldDef("gap_size",                177, "int16", "Gap size"),
    FieldDef("over_travel",             179, "int16", "Over travel associated with taper"),
)

_REV1: tuple[FieldDef, ...] = (
    FieldDef("cdp_x",                   181, "int32", "X of the ensemble position", since=(1, 0)),
    FieldDef("cdp_y",                   185, "int32", "Y of the ensemble position", since=(1, 0)),
    FieldDef("inline",                  189, "int32", "Inline number (3D)", since=(1, 0)),
    FieldDef("crossline",               193, "int32", "Crossline number (3D)", since=(1, 0)),
    FieldDef("shotpoint",               197, "int32", "Shotpoint number", since=(1, 0)),
    FieldDef("shotpoint_scalar",        201, "int16", "Scalar for the shotpoint number", since=(1, 0)),
    FieldDef("trace_value_unit",        203, "int16", "Trace value measurement unit", since=(1, 0)),
    FieldDef("transduction_mantissa",   205, "int32", "Transduction constant, mantissa", since=(1, 0)),
    FieldDef("transduction_exponent",   209, "int16", "Transduction constant, exponent", since=(1, 0)),
    FieldDef("transduction_unit",       211, "int16", "Transduction units", since=(1, 0)),
    FieldDef("device_identifier",       213, "int16", "Device / trace identifier", since=(1, 0)),
    FieldDef("times_scalar",            215, "int16", "Scalar for times in bytes 95-114", since=(1, 0)),
    FieldDef("source_type_orientation", 217, "int16", "Source type / orientation", since=(1, 0)),
    FieldDef("source_energy_mantissa",  219, "int32", "Source energy direction, mantissa", since=(1, 0)),
    FieldDef("source_energy_exponent",  223, "int16", "Source energy direction, exponent", since=(1, 0)),
    FieldDef("source_measurement_mantissa", 225, "int32", "Source measurement, mantissa", since=(1, 0)),
    FieldDef("source_measurement_exponent", 229, "int16", "Source measurement, exponent", since=(1, 0)),
    FieldDef("source_measurement_unit", 231, "int16", "Source measurement unit", since=(1, 0)),
)

#: Rev 2 names each *additional* trace header in its last eight bytes. In the
#: first header those bytes stay unassigned, which is why this is not in the
#: default table and is added only for extension blocks.
HEADER_NAME_FIELD = FieldDef(
    "trace_header_name", 233, "char8",
    "Name of this additional trace header", since=(2, 0))

_STANDARD = tuple(sorted(_REV0 + _REV1, key=lambda f: f.start))


def fields_for(major: int = 2, minor: int = 1, *,
               extension: bool = False,
               only_defined: bool = False) -> list[FieldDef]:
    """The trace-header table.

    Unlike the binary header, no trace-header field changes position or type
    between revisions — rev 1 only adds fields at bytes 181-232 and rev 2 names
    the extension blocks at 233-240. So **the full table is always readable**,
    whatever the file declares, and `since` on each field records when the
    standard defined it.

    That is a deliberate choice and it was a bug before it was a choice: half
    the deliveries that declare rev 0 carry an inline at byte 189 anyway,
    because the processor wrote one. Refusing to read it because two bytes at
    3501 say "revision 0" would be the same mistake as trusting those bytes for
    anything else.

    `only_defined=True` restricts the table to what the given revision defines,
    which is what a validator wants and a reader does not.
    """
    if extension:
        return [HEADER_NAME_FIELD]
    if only_defined:
        return [f for f in _STANDARD if f.since <= (major, minor)]
    return list(_STANDARD)


def parse(block: bytes, *, major: int = 2, minor: int = 1,
          endian: Endian = Endian.BIG, offset: int = 0,
          extension: bool = False, source: str = "trace_header") -> HeaderView:
    """Decode one 240-byte trace header block.

    `offset` is the 0-based file position of the block, used so that every
    Reading can name its absolute byte range.
    """
    readings: list[Reading] = [
        fd.read(block, endian=endian, block_offset=offset + 1, source=source)
        for fd in fields_for(major, minor, extension=extension)
    ]
    return HeaderView(readings, block=block, block_offset=offset + 1, endian=endian)


def parse_trace(blocks: list[bytes], *, major: int = 2, minor: int = 1,
                endian: Endian = Endian.BIG, offset: int = 0) -> list[HeaderView]:
    """Decode a trace's standard header and however many extensions follow it."""
    views: list[HeaderView] = []
    for i, block in enumerate(blocks):
        views.append(parse(
            block, major=major, minor=minor, endian=endian,
            offset=offset + i * TRACE_HEADER_SIZE,
            extension=i > 0,
            source="trace_header" if i == 0 else f"trace_header_ext_{i}"))
    return views


def apply_coordinate_scalar(value: int | None, scalar: int | None) -> float | None:
    """The SEG-Y scalar convention: negative divides, positive multiplies.

    Zero means "no scaling", which the standard does not say in so many words
    but every processor assumes, and a file that means it writes 1.
    """
    if value is None:
        return None
    if not scalar:
        return float(value)
    if scalar < 0:
        return value / float(-scalar)
    return value * float(scalar)
