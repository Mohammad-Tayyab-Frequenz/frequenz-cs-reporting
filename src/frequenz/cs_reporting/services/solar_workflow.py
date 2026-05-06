# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Services to prepare solar workflow requests."""

from __future__ import annotations

import datetime
import os
from typing import Any

from frequenz.gridpool import MicrogridConfig


def _build_client_site_info(config: MicrogridConfig) -> dict[str, float]:
    """Extract site metadata and PV capacity information from the microgrid configuration.

    Collects geographic metadata (latitude, longitude, altitude) and aggregates
    photovoltaic capacity figures from the provided configuration. The returned
    dictionary is intended for use by the solar workflow and downstream analytics.

    Args:
        config:
            Microgrid configuration object containing PV component definitions and
            optional site metadata.

    Returns:
            Mapping with site and PV-related parameters, including:
            - ``latitude``: Site latitude (degrees).
            - ``longitude``: Site longitude (degrees).
            - ``altitude``: Site altitude (meters).
            - ``peak_power_watts``: Sum of PV peak power across all PV components.
            - ``rated_power_watts``: Sum of PV rated power across all PV components.
            - ``efficiency``: Assumed PV efficiency factor.
    """
    pv_components = getattr(config, "pv", {}) or {}
    pv_peaks = sum(pv.peak_power for pv in pv_components.values())
    pv_rated = sum(pv.rated_power for pv in pv_components.values())

    meta = getattr(config, "meta", None)
    return {
        "latitude": getattr(meta, "latitude", 0.0) if meta else 0.0,
        "longitude": getattr(meta, "longitude", 0.0) if meta else 0.0,
        "altitude": getattr(meta, "altitude", 0.0) if meta else 0.0,
        "peak_power_watts": pv_peaks,
        "rated_power_watts": pv_rated,
        "efficiency": 0.85,
    }


# pylint: disable=too-many-arguments, too-many-locals
def build_workflow_request(
    *,
    microgrid_id: int,
    config: MicrogridConfig,
    start_date: datetime.date,
    time_zone: str,
    component_category: str,
    language: str,
    resample_period: str,
    rolling_view_duration: int,
    baseline_models: list[str],
) -> dict[str, Any]:
    """Build the request payload for triggering the solar workflow.

    Assembles all required parameters into a dictionary suitable for submitting
    a solar workflow request. This includes time boundaries, localization settings,
    component selection, site metadata, baseline configuration, and service
    endpoints derived from the environment.

    Args:
        microgrid_id:
            Identifier of the microgrid for which the workflow is executed.
        config:
            Microgrid configuration used to resolve component IDs and site metadata.
        start_date:
            Start date of the analysis period. The timestamp is normalized to
            midnight UTC.
        time_zone:
            Time zone identifier used by the workflow for localization.
        component_category:
            Component category used to filter PV component IDs.
        language:
            Human-readable language selection (e.g., "English", "Deutsch").
        resample_period:
            Large resampling period in seconds, provided as a string.
        rolling_view_duration:
            Requested rolling view duration in days. The effective duration is
            capped by the number of days since `start_date`.
        baseline_models:
            List of baseline model identifiers to be applied by the workflow.

    Returns:
            A dictionary representing the complete workflow request payload,
            including timestamps, localization options, component IDs, site
            metadata, service endpoints, and model configuration.
    """
    start_dt = datetime.datetime.combine(
        start_date, datetime.time.min, tzinfo=datetime.UTC
    )
    end_timestamp = datetime.datetime.now(tz=datetime.UTC)

    days_since_start = max(0, (end_timestamp - start_dt).days)
    actual_rolling_duration = min(rolling_view_duration, days_since_start)
    lang_code = {"English": "en", "Englisch": "en", "Deutsch": "de"}.get(language, "de")

    weather_api = os.environ.get("WEATHER_API_URL")
    reporting_api = os.environ.get("REPORTING_API_URL")

    return {
        "time_zone": time_zone,
        "start_timestamp": start_dt,
        "end_timestamp": end_timestamp,
        "rolling_view_duration": actual_rolling_duration,
        "language": lang_code,
        "weather_service_address": weather_api,
        "reporting_service_address": reporting_api,
        "microgrid_ids": [microgrid_id],
        "component_ids": [
            config.component_type_ids(
                component_type="pv", component_category=component_category
            )
        ],
        "client_site_info": [_build_client_site_info(config)],
        "baseline_models": baseline_models,
        "large_resample_period_seconds": int(resample_period),
    }
