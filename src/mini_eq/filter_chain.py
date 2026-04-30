from __future__ import annotations

from .core import (
    EQ_PREAMP_MAX_DB,
    EQ_PREAMP_MIN_DB,
    MAX_BANDS,
    OUTPUT_CLIENT_NAME,
    SAMPLE_RATE,
    VIRTUAL_SINK_DESCRIPTION,
    BiquadCoefficients,
    EqBand,
    band_biquad_coefficients,
    bands_have_solo,
    clamp,
    db_to_linear,
    identity_biquad_coefficients,
)

BIQUAD_CONTROL_NAMES = ("b0", "b1", "b2", "a0", "a1", "a2")
BIQUAD_CONFIG_SAMPLE_RATES = (44100.0, 48000.0, 96000.0, 192000.0)


def pipewire_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def spa_float(value: float) -> str:
    return f"{float(value):.8g}"


def biquad_node_name(side: str, index: int) -> str:
    return f"band_{side}_{index}"


def preamp_node_name(side: str) -> str:
    return f"preamp_{side}"


def preamp_biquad_coefficients(preamp_db: float, eq_enabled: bool) -> BiquadCoefficients:
    if not eq_enabled:
        return identity_biquad_coefficients()

    gain = db_to_linear(clamp(preamp_db, EQ_PREAMP_MIN_DB, EQ_PREAMP_MAX_DB))
    return identity_biquad_coefficients(gain).scaled_for_control_range()


def active_band_biquad_coefficients(
    band: EqBand,
    sample_rate: float,
    eq_enabled: bool,
    solo_active: bool = False,
) -> BiquadCoefficients:
    if not eq_enabled:
        return identity_biquad_coefficients()

    return band_biquad_coefficients(band, sample_rate, solo_active).scaled_for_control_range()


def biquad_coefficients_to_controls(
    node_name: str,
    coefficients: BiquadCoefficients,
) -> dict[str, float]:
    values = coefficients.as_dict()
    return {f"{node_name}:{name}": values[name] for name in BIQUAD_CONTROL_NAMES}


def builtin_biquad_preamp_control_values(
    preamp_db: float,
    eq_enabled: bool,
) -> dict[str, float]:
    coefficients = preamp_biquad_coefficients(preamp_db, eq_enabled)
    controls: dict[str, float] = {}

    for side in ("l", "r"):
        controls.update(biquad_coefficients_to_controls(preamp_node_name(side), coefficients))

    return controls


def builtin_biquad_band_control_values(
    index: int,
    band: EqBand,
    eq_enabled: bool,
    sample_rate: float = SAMPLE_RATE,
    solo_active: bool = False,
) -> dict[str, float]:
    coefficients = active_band_biquad_coefficients(band, sample_rate, eq_enabled, solo_active)
    controls: dict[str, float] = {}

    for side in ("l", "r"):
        controls.update(biquad_coefficients_to_controls(biquad_node_name(side, index), coefficients))

    return controls


def builtin_biquad_control_values(
    bands: list[EqBand],
    preamp_db: float,
    eq_enabled: bool,
    sample_rate: float = SAMPLE_RATE,
) -> dict[str, float]:
    controls = builtin_biquad_preamp_control_values(preamp_db, eq_enabled)
    solo_active = bands_have_solo(bands)

    for index, band in enumerate(bands[:MAX_BANDS]):
        controls.update(builtin_biquad_band_control_values(index, band, eq_enabled, sample_rate, solo_active))

    return controls


def format_biquad_coefficients(coefficients: BiquadCoefficients) -> str:
    values = coefficients.as_dict()
    return " ".join(f"{name} = {spa_float(values[name])}" for name in BIQUAD_CONTROL_NAMES)


def build_biquad_raw_config(coefficients_by_rate: dict[float, BiquadCoefficients]) -> str:
    coefficient_lines = "\n".join(
        f"            {{ rate = {int(rate)} {format_biquad_coefficients(coefficients)} }}"
        for rate, coefficients in coefficients_by_rate.items()
    )
    return f"""        config = {{
          coefficients = [
{coefficient_lines}
          ]
        }}"""


def build_biquad_node(
    node_name: str,
    coefficients_by_rate: dict[float, BiquadCoefficients],
) -> str:
    config = build_biquad_raw_config(coefficients_by_rate)
    return f"""      {{
        type = builtin
        name = {node_name}
        label = bq_raw
{config}
      }}"""


def preamp_coefficients_by_rate(preamp_db: float, eq_enabled: bool) -> dict[float, BiquadCoefficients]:
    coefficients = preamp_biquad_coefficients(preamp_db, eq_enabled)
    return {rate: coefficients for rate in BIQUAD_CONFIG_SAMPLE_RATES}


def band_coefficients_by_rate(
    band: EqBand,
    eq_enabled: bool,
    solo_active: bool = False,
) -> dict[float, BiquadCoefficients]:
    return {
        rate: active_band_biquad_coefficients(band, rate, eq_enabled, solo_active)
        for rate in BIQUAD_CONFIG_SAMPLE_RATES
    }


def build_builtin_biquad_nodes(
    bands: list[EqBand],
    preamp_db: float,
    eq_enabled: bool,
) -> str:
    nodes: list[str] = []
    solo_active = bands_have_solo(bands)

    for side in ("l", "r"):
        nodes.append(build_biquad_node(preamp_node_name(side), preamp_coefficients_by_rate(preamp_db, eq_enabled)))

        for index, band in enumerate(bands[:MAX_BANDS]):
            nodes.append(
                build_biquad_node(
                    biquad_node_name(side, index), band_coefficients_by_rate(band, eq_enabled, solo_active)
                )
            )

    return "\n".join(nodes)


def build_builtin_biquad_links(band_count: int) -> str:
    links: list[str] = []

    for side in ("l", "r"):
        previous = preamp_node_name(side)

        for index in range(band_count):
            current = biquad_node_name(side, index)
            links.append(f'      {{ output = "{previous}:Out" input = "{current}:In" }}')
            previous = current

    return "\n".join(links)


def build_builtin_biquad_filter_chain_module_args(
    *,
    bands: list[EqBand],
    preamp_db: float,
    eq_enabled: bool,
    virtual_sink_name: str,
    filter_output_name: str,
    output_sink: str,
) -> str:
    graph_bands = bands[:MAX_BANDS]
    band_count = len(graph_bands)
    nodes = build_builtin_biquad_nodes(graph_bands, preamp_db, eq_enabled)
    links = build_builtin_biquad_links(band_count)
    output_l = biquad_node_name("l", band_count - 1) if band_count else preamp_node_name("l")
    output_r = biquad_node_name("r", band_count - 1) if band_count else preamp_node_name("r")

    return f"""{{
  node.description = {pipewire_quote(VIRTUAL_SINK_DESCRIPTION)}
  media.name = {pipewire_quote(VIRTUAL_SINK_DESCRIPTION)}
  filter.graph = {{
    nodes = [
{nodes}
    ]
    links = [
{links}
    ]
    inputs = [ "{preamp_node_name("l")}:In" "{preamp_node_name("r")}:In" ]
    outputs = [ "{output_l}:Out" "{output_r}:Out" ]
  }}
  audio.channels = 2
  audio.position = [ FL FR ]
  capture.props = {{
    node.name = {pipewire_quote(virtual_sink_name)}
    node.description = {pipewire_quote(VIRTUAL_SINK_DESCRIPTION)}
    media.class = Audio/Sink
    audio.channels = 2
    audio.position = [ FL FR ]
  }}
  playback.props = {{
    node.name = {pipewire_quote(filter_output_name)}
    node.description = {pipewire_quote(OUTPUT_CLIENT_NAME)}
    node.passive = true
    target.object = {pipewire_quote(output_sink)}
    audio.channels = 2
    audio.position = [ FL FR ]
  }}
}}
"""
