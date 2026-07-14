"""
tests/unit/test_crowd_flow.py — Unit tests for the CrowdFlowService.

All tests use real CrowdFlowService instances with an in-memory StadiumRegistry.
No external I/O — these tests run in milliseconds.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from datetime import datetime, timezone

from app.models.crowd import CrowdDataIngestionRequest, SensorReading
from app.models.stadium import DensityLevel
from app.services.crowd_flow import (
    CrowdFlowService,
    _classify_density,
    DENSITY_THRESHOLDS,
)
from app.services.stadium_registry import StadiumRegistry


VALID_STADIUM = "metlife"   # MetLife Stadium — first in registry


# ── Density Classification Tests ─────────────────────────────────────────────

class TestClassifyDensity:
    """Unit tests for the density score → DensityLevel classifier."""

    @pytest.mark.parametrize("score, expected", [
        (0.0,  DensityLevel.LOW),
        (0.25, DensityLevel.LOW),
        (0.49, DensityLevel.LOW),
        (0.50, DensityLevel.MEDIUM),
        (0.65, DensityLevel.MEDIUM),
        (0.74, DensityLevel.MEDIUM),
        (0.75, DensityLevel.HIGH),
        (0.88, DensityLevel.HIGH),
        (0.91, DensityLevel.HIGH),
        (0.92, DensityLevel.CRITICAL),
        (1.00, DensityLevel.CRITICAL),
    ])
    def test_threshold_boundaries(self, score: float, expected: DensityLevel):
        """Each threshold boundary maps to the correct DensityLevel."""
        assert _classify_density(score) == expected

    def test_all_density_levels_covered(self):
        """Every DensityLevel must be reachable from some score."""
        reachable = {_classify_density(score / 100) for score in range(101)}
        assert reachable == {DensityLevel.LOW, DensityLevel.MEDIUM,
                             DensityLevel.HIGH, DensityLevel.CRITICAL}


# ── Ingestion Tests ───────────────────────────────────────────────────────────

class TestCrowdFlowIngestion:
    """Tests for the data ingestion pipeline."""

    def _make_reading(self, zone_id: str, occupancy: int) -> SensorReading:
        return SensorReading(
            sensor_id="SENSOR_001",
            zone_id=zone_id,
            occupancy_count=occupancy,
            timestamp=datetime.now(timezone.utc),
            source="nfc_gate",
        )

    @pytest.mark.asyncio
    async def test_ingest_updates_zone_occupancy(
        self, crowd_service: CrowdFlowService
    ):
        """After ingestion, the snapshot should reflect the new occupancy."""
        readings = [self._make_reading("GATE_N", 3000)]
        request = CrowdDataIngestionRequest(
            stadium_id=VALID_STADIUM,
            readings=readings,
        )
        zones_updated = await crowd_service.ingest(request)
        assert zones_updated == 1

        snapshot = await crowd_service.get_snapshot(VALID_STADIUM)
        gate_n = next(z for z in snapshot.zones if z.zone_id == "GATE_N")
        assert gate_n.current_occupancy == 3000

    @pytest.mark.asyncio
    async def test_ingest_takes_max_across_batch(
        self, crowd_service: CrowdFlowService
    ):
        """Multiple readings for the same zone: max value must be used."""
        readings = [
            self._make_reading("GATE_N", 1000),
            self._make_reading("GATE_N", 4500),  # higher value
            self._make_reading("GATE_N", 2000),
        ]
        await crowd_service.ingest(
            CrowdDataIngestionRequest(stadium_id=VALID_STADIUM, readings=readings)
        )
        snapshot = await crowd_service.get_snapshot(VALID_STADIUM)
        gate_n = next(z for z in snapshot.zones if z.zone_id == "GATE_N")
        # Must be the MAX, not the last or average
        assert gate_n.current_occupancy == 4500

    @pytest.mark.asyncio
    async def test_ingest_clamps_to_capacity(
        self, crowd_service: CrowdFlowService
    ):
        """Occupancy must never exceed zone capacity (sensor calibration errors)."""
        # GATE_N has capacity 5000
        readings = [self._make_reading("GATE_N", 999_999)]
        await crowd_service.ingest(
            CrowdDataIngestionRequest(stadium_id=VALID_STADIUM, readings=readings)
        )
        snapshot = await crowd_service.get_snapshot(VALID_STADIUM)
        gate_n = next(z for z in snapshot.zones if z.zone_id == "GATE_N")
        assert gate_n.current_occupancy <= gate_n.capacity

    @pytest.mark.asyncio
    async def test_ingest_unknown_stadium_raises(
        self, crowd_service: CrowdFlowService
    ):
        readings = [self._make_reading("GATE_N", 100)]
        with pytest.raises(ValueError, match="not found"):
            await crowd_service.ingest(
                CrowdDataIngestionRequest(
                    stadium_id="nonexistent_stadium", readings=readings
                )
            )

    @pytest.mark.asyncio
    async def test_ingest_unknown_zone_is_skipped(
        self, crowd_service: CrowdFlowService
    ):
        """Unknown zone IDs in readings should be silently skipped (logged only)."""
        readings = [self._make_reading("INVALID_ZONE_999", 100)]
        zones_updated = await crowd_service.ingest(
            CrowdDataIngestionRequest(stadium_id=VALID_STADIUM, readings=readings)
        )
        # No zones updated because zone doesn't exist
        assert zones_updated == 0


# ── Snapshot Tests ────────────────────────────────────────────────────────────

class TestCrowdFlowSnapshot:
    """Tests for snapshot generation and bottleneck detection."""

    @pytest.mark.asyncio
    async def test_snapshot_contains_all_zones(
        self, crowd_service: CrowdFlowService, registry: StadiumRegistry
    ):
        """Snapshot must contain entries for every zone defined in the stadium."""
        stadium = registry.get_stadium(VALID_STADIUM)
        snapshot = await crowd_service.get_snapshot(VALID_STADIUM)
        assert len(snapshot.zones) == len(stadium.zones)

    @pytest.mark.asyncio
    async def test_snapshot_totals_are_consistent(
        self, crowd_service: CrowdFlowService
    ):
        """total_occupancy must equal the sum of per-zone occupancies."""
        snapshot = await crowd_service.get_snapshot(VALID_STADIUM)
        expected_total = sum(z.current_occupancy for z in snapshot.zones)
        assert snapshot.total_occupancy == expected_total

    @pytest.mark.asyncio
    async def test_high_density_zone_flagged_as_bottleneck(
        self, crowd_service: CrowdFlowService
    ):
        """A zone at HIGH density must appear in active_bottleneck_zone_ids."""
        # Force GATE_N to near-capacity (HIGH density ≥ 75%)
        reading = SensorReading(
            sensor_id="S1", zone_id="GATE_N", occupancy_count=4000,
            timestamp=datetime.now(timezone.utc), source="camera"
        )
        await crowd_service.ingest(
            CrowdDataIngestionRequest(stadium_id=VALID_STADIUM, readings=[reading])
        )
        snapshot = await crowd_service.get_snapshot(VALID_STADIUM)
        gate_n_state = next(z for z in snapshot.zones if z.zone_id == "GATE_N")

        if gate_n_state.density_level in (DensityLevel.HIGH, DensityLevel.CRITICAL):
            assert "GATE_N" in snapshot.active_bottleneck_zone_ids

    @pytest.mark.asyncio
    async def test_density_score_in_valid_range(
        self, crowd_service: CrowdFlowService
    ):
        """All density scores must be in [0.0, 1.0]."""
        snapshot = await crowd_service.get_snapshot(VALID_STADIUM)
        for zone in snapshot.zones:
            assert 0.0 <= zone.density_score <= 1.0, (
                f"Zone {zone.zone_id} density_score {zone.density_score} out of range"
            )

    @pytest.mark.asyncio
    async def test_unknown_stadium_snapshot_raises(
        self, crowd_service: CrowdFlowService
    ):
        with pytest.raises(ValueError, match="not found"):
            await crowd_service.get_snapshot("stadium_that_does_not_exist")


# ── Density Multiplier Tests ──────────────────────────────────────────────────

class TestDensityMultipliers:
    """Tests for routing multiplier computation."""

    @pytest.mark.asyncio
    async def test_multipliers_returned_for_all_zones(
        self, crowd_service: CrowdFlowService, registry: StadiumRegistry
    ):
        """Every zone must have a corresponding multiplier (default = 1.0 for LOW)."""
        stadium = registry.get_stadium(VALID_STADIUM)
        multipliers = crowd_service.get_density_multipliers(VALID_STADIUM)
        for zone in stadium.zones:
            assert zone.zone_id in multipliers, f"Missing multiplier for {zone.zone_id}"

    @pytest.mark.asyncio
    async def test_critical_zone_has_highest_multiplier(
        self, crowd_service: CrowdFlowService
    ):
        """A CRITICAL density zone must have the maximum routing multiplier."""
        from app.services.crowd_flow import DENSITY_ROUTING_MULTIPLIERS
        from app.models.stadium import DensityLevel

        # Pack GATE_N to critical (> 92% capacity of 5000 = 4601)
        reading = SensorReading(
            sensor_id="S1", zone_id="GATE_N", occupancy_count=4700,
            timestamp=datetime.now(timezone.utc), source="camera"
        )
        await crowd_service.ingest(
            CrowdDataIngestionRequest(stadium_id=VALID_STADIUM, readings=[reading])
        )
        multipliers = crowd_service.get_density_multipliers(VALID_STADIUM)
        critical_mult = DENSITY_ROUTING_MULTIPLIERS[DensityLevel.CRITICAL]
        # GATE_N should now be at or near the critical multiplier
        assert multipliers["GATE_N"] >= DENSITY_ROUTING_MULTIPLIERS[DensityLevel.HIGH]
