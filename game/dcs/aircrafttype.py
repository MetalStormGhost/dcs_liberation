from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import ClassVar, Type, Iterator, TYPE_CHECKING, Optional, Any

import yaml
from dcs.helicopters import helicopter_map
from dcs.planes import plane_map
from dcs.unittype import FlyingType

from game.radio.channels import (
    ChannelNamer,
    RadioChannelAllocator,
    CommonRadioChannelAllocator,
)
from game.utils import Speed, kph

if TYPE_CHECKING:
    from gen.aircraft import FlightData
    from gen import AirSupport, RadioFrequency, RadioRegistry
    from gen.radios import Radio


@dataclass(frozen=True)
class RadioConfig:
    inter_flight: Optional[Radio]
    intra_flight: Optional[Radio]
    channel_allocator: Optional[RadioChannelAllocator]
    channel_namer: Type[ChannelNamer]

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> RadioConfig:
        return RadioConfig(
            cls.make_radio(data.get("inter_flight", None)),
            cls.make_radio(data.get("intra_flight", None)),
            cls.make_allocator(data.get("channels", {})),
            cls.make_namer(data.get("channels", {})),
        )

    @classmethod
    def make_radio(cls, name: Optional[str]) -> Optional[Radio]:
        from gen.radios import get_radio

        if name is None:
            return None
        return get_radio(name)

    @classmethod
    def make_allocator(cls, data: dict[str, Any]) -> Optional[RadioChannelAllocator]:
        try:
            alloc_type = data["type"]
        except KeyError:
            return None
        return {"common": CommonRadioChannelAllocator}[alloc_type].from_cfg(data)

    @classmethod
    def make_namer(cls, config: dict[str, Any]) -> Type[ChannelNamer]:
        return {"default": ChannelNamer}[config.get("namer", "default")]


@dataclass(frozen=True)
class AircraftType:
    dcs_unit_type: Type[FlyingType]
    name: str
    description: str
    price: int
    carrier_capable: bool
    lha_capable: bool
    always_keeps_gun: bool
    intra_flight_radio: Optional[Radio]
    channel_allocator: Optional[RadioChannelAllocator]
    channel_namer: Type[ChannelNamer]

    _by_name: ClassVar[dict[str, AircraftType]] = {}
    _by_unit_type: ClassVar[dict[Type[FlyingType], list[AircraftType]]] = defaultdict(
        list
    )
    _loaded: ClassVar[bool] = False

    def __str__(self) -> str:
        return self.name

    @property
    def dcs_id(self) -> str:
        return self.dcs_unit_type.id

    @property
    def flyable(self) -> bool:
        return self.dcs_unit_type.flyable

    @cached_property
    def max_speed(self) -> Speed:
        return kph(self.dcs_unit_type.max_speed)

    def alloc_flight_radio(self, radio_registry: RadioRegistry) -> RadioFrequency:
        from gen.radios import ChannelInUseError, MHz

        if self.intra_flight_radio is not None:
            return radio_registry.alloc_for_radio(self.intra_flight_radio)

        freq = MHz(self.dcs_unit_type.radio_frequency)
        try:
            radio_registry.reserve(freq)
        except ChannelInUseError:
            pass
        return freq

    def assign_channels_for_flight(
        self, flight: FlightData, air_support: AirSupport
    ) -> None:
        if self.channel_allocator is not None:
            self.channel_allocator.assign_channels_for_flight(flight, air_support)

    def channel_name(self, radio_id: int, channel_id: int) -> str:
        return self.channel_namer.channel_name(radio_id, channel_id)

    @classmethod
    def register(cls, aircraft_type: AircraftType) -> None:
        cls._by_name[aircraft_type.name] = aircraft_type
        cls._by_unit_type[aircraft_type.dcs_unit_type].append(aircraft_type)

    @classmethod
    def named(cls, name: str) -> AircraftType:
        if not cls._loaded:
            cls._load_all()
        return cls._by_name[name]

    @classmethod
    def for_dcs_type(cls, dcs_unit_type: Type[FlyingType]) -> Iterator[AircraftType]:
        yield from cls._by_unit_type[dcs_unit_type]

    @staticmethod
    def _each_unit_type() -> Iterator[Type[FlyingType]]:
        yield from helicopter_map.values()
        yield from plane_map.values()

    @classmethod
    def _load_all(cls) -> None:
        for unit_type in cls._each_unit_type():
            for data in cls._each_variant_of(unit_type):
                cls.register(data)
        cls._loaded = True

    @classmethod
    def _each_variant_of(cls, aircraft: Type[FlyingType]) -> Iterator[AircraftType]:
        data_path = Path("resources/units/aircraft") / f"{aircraft.id}.yaml"
        if not data_path.exists():
            logging.warning(f"No data for {aircraft.id}; it will not be available")
            return

        with data_path.open() as data_file:
            data = yaml.safe_load(data_file)

        try:
            price = data["price"]
        except KeyError as ex:
            raise KeyError(f"Missing required price field: {data_path}") from ex

        radio_config = RadioConfig.from_data(data.get("radios", {}))

        for variant in data.get("variants", [aircraft.id]):
            yield AircraftType(
                dcs_unit_type=aircraft,
                name=variant,
                description=data.get("description", "No data."),
                price=price,
                carrier_capable=data.get("carrier_capable", False),
                lha_capable=data.get("lha_capable", False),
                always_keeps_gun=data.get("always_keeps_gun", False),
                intra_flight_radio=radio_config.intra_flight,
                channel_allocator=radio_config.channel_allocator,
                channel_namer=radio_config.channel_namer,
            )