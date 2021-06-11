"""
Briefing generation logic
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta
from typing import Dict, List, TYPE_CHECKING

from dcs.mission import Mission
from jinja2 import Environment, FileSystemLoader, select_autoescape

from game.theater import ControlPoint, FrontLine
from .aircraft import FlightData
from .airsupportgen import AwacsInfo, TankerInfo
from .armor import JtacInfo
from .flights.flight import FlightWaypoint
from .ground_forces.combat_stance import CombatStance
from .radios import RadioFrequency
from .runways import RunwayData


if TYPE_CHECKING:
    from game import Game


@dataclass
class CommInfo:
    """Communications information for the kneeboard."""

    name: str
    freq: RadioFrequency


class FrontLineInfo:
    def __init__(self, front_line: FrontLine):
        self.front_line: FrontLine = front_line
        self.player_base: ControlPoint = front_line.blue_cp
        self.enemy_base: ControlPoint = front_line.red_cp
        self.player_zero: bool = self.player_base.base.total_armor == 0
        self.enemy_zero: bool = self.enemy_base.base.total_armor == 0
        self.advantage: bool = (
            self.player_base.base.total_armor > self.enemy_base.base.total_armor
        )
        self.stance: CombatStance = self.player_base.stances[self.enemy_base.id]
        self.combat_stances = CombatStance


class MissionInfoGenerator:
    """Base type for generators of mission information for the player.

    Examples of subtypes include briefing generators, kneeboard generators, etc.
    """

    def __init__(self, mission: Mission, game: Game) -> None:
        self.mission = mission
        self.game = game
        self.awacs: List[AwacsInfo] = []
        self.comms: List[CommInfo] = []
        self.flights: List[FlightData] = []
        self.jtacs: List[JtacInfo] = []
        self.tankers: List[TankerInfo] = []
        self.frontlines: List[FrontLineInfo] = []
        self.dynamic_runways: List[RunwayData] = []

    def add_awacs(self, awacs: AwacsInfo) -> None:
        """Adds an AWACS/GCI to the mission.

        Args:
            awacs: AWACS information.
        """
        self.awacs.append(awacs)

    def add_comm(self, name: str, freq: RadioFrequency) -> None:
        """Adds communications info to the mission.

        Args:
            name: Name of the radio channel.
            freq: Frequency of the radio channel.
        """
        self.comms.append(CommInfo(name, freq))

    def add_flight(self, flight: FlightData) -> None:
        """Adds flight info to the mission.

        Args:
            flight: Flight information.
        """
        self.flights.append(flight)

    def add_jtac(self, jtac: JtacInfo) -> None:
        """Adds a JTAC to the mission.

        Args:
            jtac: JTAC information.
        """
        self.jtacs.append(jtac)

    def add_tanker(self, tanker: TankerInfo) -> None:
        """Adds a tanker to the mission.

        Args:
            tanker: Tanker information.
        """
        self.tankers.append(tanker)

    def add_frontline(self, frontline: FrontLineInfo) -> None:
        """Adds a frontline to the briefing

        Arguments:
            frontline: Frontline conflict information
        """
        self.frontlines.append(frontline)

    def add_dynamic_runway(self, runway: RunwayData) -> None:
        """Adds a dynamically generated runway to the briefing.

        Dynamic runways are any valid landing point that is a unit rather than a
        map feature. These include carriers, ships with a helipad, and FARPs.
        """
        self.dynamic_runways.append(runway)

    def generate(self) -> None:
        """Generates the mission information."""
        raise NotImplementedError


def format_waypoint_time(waypoint: FlightWaypoint, depart_prefix: str) -> str:
    if waypoint.tot is not None:
        time = timedelta(seconds=int(waypoint.tot.total_seconds()))
        return f"T+{time} "
    elif waypoint.departure_time is not None:
        time = timedelta(seconds=int(waypoint.departure_time.total_seconds()))
        return f"{depart_prefix} T+{time} "
    return ""


class BriefingGenerator(MissionInfoGenerator):
    def __init__(self, mission: Mission, game: Game):
        super().__init__(mission, game)
        self.allied_flights_by_departure: Dict[str, List[FlightData]] = {}
        env = Environment(
            loader=FileSystemLoader("resources/briefing/templates"),
            autoescape=select_autoescape(
                disabled_extensions=("",),
                default_for_string=True,
                default=True,
            ),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        env.filters["waypoint_timing"] = format_waypoint_time
        self.template = env.get_template("briefingtemplate_EN.j2")

    def generate(self) -> None:
        """Generate the mission briefing"""
        self._generate_frontline_info()
        self.generate_allied_flights_by_departure()
        self.mission.set_description_text(self.template.render(vars(self)))
        self.mission.add_picture_blue(
            os.path.abspath("./resources/ui/splash_screen.png")
        )

    def _generate_frontline_info(self) -> None:
        """Build FrontLineInfo objects from FrontLine type and append to briefing."""
        for front_line in self.game.theater.conflicts():
            self.add_frontline(FrontLineInfo(front_line))

    # TODO: This should determine if runway is friendly through a method more robust than the existing string match
    def generate_allied_flights_by_departure(self) -> None:
        """Create iterable to display allied flights grouped by departure airfield."""
        for flight in self.flights:
            if not flight.client_units and flight.friendly:
                name = flight.departure.airfield_name
                if (
                    name in self.allied_flights_by_departure
                ):  # where else can we get this?
                    self.allied_flights_by_departure[name].append(flight)
                else:
                    self.allied_flights_by_departure[name] = [flight]
