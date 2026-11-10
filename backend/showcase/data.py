"""Definition of the synthetic demonstration dataset (organisations, projects, spare parts, users).

Everything here is fictitious and marked as a sample. Part numbers use the prefixes DME/DIM/DES; organisation
slugs start with "demo-"; demo user emails end in ".demo". Scenarios describe how much passport data is captured:
  none      - passport with incomplete R-L1 data
  rl1       - R-L1 data complete
  rl2       - R-L1 and R-L2 data complete
  rl3docs   - R-L1 and R-L2 complete and the five R-L3 evidence documents attached (NOT QA-verified)
  nopass    - spare part without a passport
Official evidence level, publication and manufacturing eligibility are never set by the seed (OQ-35/OQ-36).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PartDef:
    number: str
    name: str
    family: str
    params: dict
    project: str
    scenario: str
    material: str
    proposed: str
    criticality: str = "non_critical"
    category: str = "mechanical"
    motion: str = "static"
    rpm: str = ""
    atmosphere: str = "non_corrosive"
    application: str = ""
    equipment: str = ""
    description: str = ""
    status: str = "active"
    docs: bool = True          # False: no documents at all (shows "parts without documents")
    spec_v2: bool = False      # upload a revised specification (version history)


@dataclass
class ClientDef:
    slug: str
    name: str
    prefix: str
    domain: str
    sector: str
    projects: list[tuple[str, str, str]]
    parts: list[PartDef] = field(default_factory=list)
    admin: tuple[str, str] = ("", "")
    user: tuple[str, str] = ("", "")


MATERIALS = {
    # proposed AM material -> (feedstock, process, heat treatment, standard reference, acceptance rows)
    "SS 316L": ("316L powder, 15-45 µm (sample lot)", "L-PBF", "Stress relief 650 °C / 2 h (sample)", "ASTM F3184 (reference only)",
                [("tensile", "≥ 485", "MPa", "ISO 6892-1"), ("yield", "≥ 170", "MPa", "ISO 6892-1"),
                 ("elongation", "≥ 30", "%", "ISO 6892-1"), ("hardness", "≤ 95", "HRB", "ISO 6508-1")]),
    "17-4 PH": ("17-4 PH powder, 15-45 µm (sample lot)", "L-PBF", "Solution + H1150 ageing (sample)", "ASTM F3184 (reference only)",
                [("tensile", "≥ 930", "MPa", "ISO 6892-1"), ("yield", "≥ 725", "MPa", "ISO 6892-1"),
                 ("elongation", "≥ 16", "%", "ISO 6892-1"), ("hardness", "28-37", "HRC", "ISO 6508-1")]),
    "Inconel 625": ("Alloy 625 powder, 15-53 µm (sample lot)", "L-PBF", "Stress relief 870 °C / 1 h (sample)", "ASTM F3056 (reference only)",
                    [("tensile", "≥ 827", "MPa", "ISO 6892-1"), ("yield", "≥ 414", "MPa", "ISO 6892-1"),
                     ("elongation", "≥ 30", "%", "ISO 6892-1")]),
    "AlSi10Mg": ("AlSi10Mg powder, 20-63 µm (sample lot)", "L-PBF", "Stress relief 300 °C / 2 h (sample)", "ASTM F3318 (reference only)",
                 [("tensile", "≥ 300", "MPa", "ISO 6892-1"), ("yield", "≥ 200", "MPa", "ISO 6892-1"),
                  ("elongation", "≥ 4", "%", "ISO 6892-1")]),
}

P = PartDef

MARITIME = ClientDef(
    "demo-maritime", "Demo Maritime Engineering", "DME", "maritime.demo", "Ship equipment and marine spare parts",
    [("DME-P01", "Auxiliary sea-water pump refit (sample)", "Digitisation of spare parts for the auxiliary sea-water pumps of a fictitious vessel class."),
     ("DME-P02", "Deck machinery spares (sample)", "Windlass and mooring winch spare parts captured as digital passports."),
     ("DME-P03", "Engine-room ventilation spares (sample)", "Fan and damper components for the engine-room ventilation system.")],
    [
        P("DME-1001", "Sea-water pump impeller, 6 vanes", "pump_impeller", dict(d=165, hub_d=50, bore=24, blades=6, height=44), "DME-P01", "rl3docs",
          "Bronze CC491K (sample)", "SS 316L", "critical", motion="rotating", rpm="1750", atmosphere="corrosive",
          application="Auxiliary sea-water cooling pump", equipment="SWP-A2 (fictitious)", spec_v2=True),
        P("DME-1002", "Sea-water pump casing cover", "pump_cover", dict(d=240, t=20, boss_d=82, boss_h=30, bolts=12, seal_bore=42), "DME-P01", "rl2",
          "Bronze CC491K (sample)", "SS 316L", atmosphere="corrosive", application="Auxiliary sea-water cooling pump", equipment="SWP-A2 (fictitious)"),
        P("DME-1003", "Pump shaft spacer sleeve", "spacer_sleeve", dict(od=48, id_=32, length=36, chamfer=1.5), "DME-P01", "rl1",
          "AISI 316 (sample)", "SS 316L", atmosphere="corrosive", application="Auxiliary sea-water cooling pump shaft", equipment="SWP-A2 (fictitious)"),
        P("DME-1004", "Coupling half, motor side", "shaft_coupling", dict(d=120, hub_d=64, bore=35, hub_len=55, flange_t=16, bolts=6), "DME-P01", "rl2",
          "EN-GJS-400 (sample)", "17-4 PH", motion="rotating", rpm="1750", application="Pump to motor coupling", equipment="SWP-A2 (fictitious)"),
        P("DME-1005", "Windlass bearing housing", "bearing_housing", dict(bore=70, length=190, height=105, base_t=24, width=64), "DME-P02", "rl1",
          "EN-GJL-250 (sample)", "17-4 PH", "critical", atmosphere="corrosive", application="Anchor windlass main shaft support", equipment="WL-3 (fictitious)"),
        P("DME-1006", "Mooring winch gear housing", "gear_housing", dict(lx=220, ly=150, lz=120, wall=10, shafts=2), "DME-P02", "none",
          "EN-GJL-250 (sample)", "AlSi10Mg", atmosphere="corrosive", application="Mooring winch reduction gear", equipment="MW-1 (fictitious)"),
        P("DME-1007", "Hydraulic line flange DN80", "pipe_flange", dict(d=200, bore=80, t=22, neck_d=110, neck_len=42, bolts=8), "DME-P02", "rl2",
          "S355 (sample)", "SS 316L", atmosphere="corrosive", application="Deck hydraulic supply line", equipment="HYD-DK (fictitious)"),
        P("DME-1008", "Deck-light mounting bracket", "bracket", dict(w=110, h=80, t=8, depth=55, holes=2), "DME-P02", "none",
          "S235 galvanised (sample)", "AlSi10Mg", atmosphere="corrosive", application="Deck floodlight mounting", docs=False),
        P("DME-1009", "Ventilation fan hub", "fan_hub", dict(d=150, hub_d=56, bore=24, arms=6, t=14, arm_w=18), "DME-P03", "rl1",
          "EN AC-43000 (sample)", "AlSi10Mg", motion="rotating", rpm="1450", application="Engine-room supply fan", equipment="ERV-F2 (fictitious)"),
        P("DME-1010", "Damper actuator bracket", "bracket", dict(w=90, h=70, t=6, depth=45, holes=3), "DME-P03", "nopass",
          "S235 (sample)", "AlSi10Mg", application="Fire damper actuator mounting", status="draft"),
        P("DME-1011", "Fan shaft thrust collar", "thrust_collar", dict(od=90, id_=45, t=20, holes=4), "DME-P03", "rl2",
          "C45 (sample)", "17-4 PH", motion="rotating", rpm="1450", application="Engine-room supply fan shaft", equipment="ERV-F2 (fictitious)"),
    ],
    admin=("Marina", "Demo-Admin"), user=("Sven", "Demo-User"),
)

INDUSTRIAL = ClientDef(
    "demo-industrial", "Demo Industrial Manufacturing", "DIM", "industrial.demo", "Pumps, valves and mechanical equipment",
    [("DIM-P01", "Process pump line PL-2 (sample)", "Spare parts of a fictitious process pump line, captured for on-demand manufacturing studies."),
     ("DIM-P02", "Valve station VS-4 spares (sample)", "Valve bodies, flanges and actuator brackets of a fictitious valve station."),
     ("DIM-P03", "Conveyor gearbox spares (sample)", "Gearbox housing and bearing components of a fictitious conveyor drive.")],
    [
        P("DIM-2001", "Process pump impeller, 7 vanes", "pump_impeller", dict(d=200, hub_d=58, bore=28, blades=7, height=50), "DIM-P01", "rl3docs",
          "CF8M (sample)", "SS 316L", "critical", motion="rotating", rpm="2900", atmosphere="corrosive",
          application="Process transfer pump", equipment="PL2-P101 (fictitious)", spec_v2=True),
        P("DIM-2002", "Pump back plate cover", "pump_cover", dict(d=260, t=22, boss_d=90, boss_h=34, bolts=12, seal_bore=45), "DIM-P01", "rl2",
          "CF8M (sample)", "SS 316L", atmosphere="corrosive", application="Process transfer pump", equipment="PL2-P101 (fictitious)", spec_v2=True),
        P("DIM-2003", "Pump shaft sleeve", "spacer_sleeve", dict(od=55, id_=40, length=60, chamfer=2), "DIM-P01", "rl2",
          "AISI 420 (sample)", "17-4 PH", motion="rotating", rpm="2900", application="Process transfer pump shaft seal area", equipment="PL2-P101 (fictitious)"),
        P("DIM-2004", "Flexible coupling hub", "shaft_coupling", dict(d=130, hub_d=70, bore=40, hub_len=60, flange_t=18, bolts=8), "DIM-P01", "rl1",
          "C45 (sample)", "17-4 PH", motion="rotating", rpm="2900", application="Pump to motor coupling", equipment="PL2-P101 (fictitious)"),
        P("DIM-2005", "Globe valve body DN50", "valve_body", dict(dn=50, length=150, flange_d=165, flange_t=18, bolts=4), "DIM-P02", "rl2",
          "CF8M (sample)", "Inconel 625", "critical", atmosphere="corrosive", application="Process isolation valve", equipment="VS4-V12 (fictitious)"),
        P("DIM-2006", "Globe valve body DN40", "valve_body", dict(dn=40, length=130, flange_d=150, flange_t=16, bolts=4), "DIM-P02", "rl1",
          "CF8M (sample)", "Inconel 625", "critical", atmosphere="corrosive", application="Process bypass valve", equipment="VS4-V14 (fictitious)"),
        P("DIM-2007", "Valve outlet flange DN65", "pipe_flange", dict(d=185, bore=66, t=20, neck_d=95, neck_len=40, bolts=4), "DIM-P02", "none",
          "P250GH (sample)", "SS 316L", application="Valve outlet spool", equipment="VS4-V12 (fictitious)"),
        P("DIM-2008", "Actuator mounting bracket", "bracket", dict(w=140, h=100, t=12, depth=70, holes=2), "DIM-P02", "rl1",
          "S355 (sample)", "17-4 PH", application="Pneumatic actuator mounting", equipment="VS4-A12 (fictitious)"),
        P("DIM-2009", "Conveyor gearbox housing", "gear_housing", dict(lx=240, ly=160, lz=130, wall=12, shafts=3), "DIM-P03", "rl2",
          "EN-GJL-250 (sample)", "AlSi10Mg", application="Belt conveyor drive gearbox", equipment="CV-G3 (fictitious)"),
        P("DIM-2010", "Gearbox output bearing housing", "bearing_housing", dict(bore=55, length=150, height=85, base_t=20, width=52), "DIM-P03", "none",
          "EN-GJL-250 (sample)", "17-4 PH", application="Conveyor drive output shaft", equipment="CV-G3 (fictitious)"),
        P("DIM-2011", "Idler shaft thrust collar", "thrust_collar", dict(od=100, id_=50, t=22, holes=6), "DIM-P03", "nopass",
          "C45 (sample)", "17-4 PH", motion="rotating", rpm="120", application="Conveyor idler shaft", status="draft"),
    ],
    admin=("Ines", "Demo-Admin"), user=("Pavel", "Demo-User"),
)

ENERGY = ClientDef(
    "demo-energy", "Demo Energy Systems", "DES", "energy.demo", "Power generation and energy equipment",
    [("DES-P01", "Gas turbine auxiliary skid (sample)", "Lube-oil and ventilation spares of a fictitious gas turbine auxiliary skid."),
     ("DES-P02", "Cooling-water system spares (sample)", "Pump, valve and flange spares of a fictitious closed cooling-water system.")],
    [
        P("DES-3001", "Lube-oil pump impeller, 5 vanes", "pump_impeller", dict(d=120, hub_d=40, bore=18, blades=5, height=34), "DES-P01", "rl3docs",
          "CF8M (sample)", "SS 316L", "critical", motion="rotating", rpm="3600", application="Turbine lube-oil circulation pump",
          equipment="GT-LO-P1 (fictitious)", spec_v2=True),
        P("DES-3002", "Lube-oil pump cover", "pump_cover", dict(d=180, t=18, boss_d=60, boss_h=26, bolts=8, seal_bore=30), "DES-P01", "rl2",
          "EN-GJS-400 (sample)", "SS 316L", application="Turbine lube-oil circulation pump", equipment="GT-LO-P1 (fictitious)"),
        P("DES-3003", "Enclosure fan hub", "fan_hub", dict(d=170, hub_d=60, bore=28, arms=4, t=16, arm_w=22), "DES-P01", "rl2",
          "EN AC-43000 (sample)", "AlSi10Mg", motion="rotating", rpm="1480", application="Turbine enclosure ventilation fan", equipment="GT-EV-F1 (fictitious)"),
        P("DES-3004", "Oil-mist separator bracket", "bracket", dict(w=100, h=120, t=10, depth=50, holes=2), "DES-P01", "rl1",
          "S235 (sample)", "AlSi10Mg", application="Lube-oil tank vent separator support", equipment="GT-LO-T1 (fictitious)"),
        P("DES-3005", "Auxiliary gearbox housing", "gear_housing", dict(lx=180, ly=130, lz=100, wall=9, shafts=2), "DES-P01", "none",
          "EN-GJL-250 (sample)", "AlSi10Mg", application="Accessory drive gearbox", equipment="GT-AGB (fictitious)"),
        P("DES-3006", "Cooling-water pump impeller, 8 vanes", "pump_impeller", dict(d=220, hub_d=64, bore=32, blades=8, height=56), "DES-P02", "rl2",
          "CC491K (sample)", "SS 316L", "critical", motion="rotating", rpm="1480", atmosphere="corrosive",
          application="Closed cooling-water circulation pump", equipment="CCW-P2 (fictitious)"),
        P("DES-3007", "Cooling-water line flange DN100", "pipe_flange", dict(d=230, bore=100, t=24, neck_d=135, neck_len=50, bolts=8), "DES-P02", "rl1",
          "P250GH (sample)", "SS 316L", atmosphere="corrosive", application="Cooling-water header", equipment="CCW-H1 (fictitious)"),
        P("DES-3008", "Cooling-water valve body DN65", "valve_body", dict(dn=65, length=180, flange_d=185, flange_t=20, bolts=4), "DES-P02", "rl2",
          "CF8M (sample)", "Inconel 625", "critical", atmosphere="corrosive", application="Heat-exchanger isolation valve", equipment="CCW-V7 (fictitious)"),
        P("DES-3009", "Cooling-water pump bearing housing", "bearing_housing", dict(bore=80, length=210, height=120, base_t=26, width=72), "DES-P02", "rl1",
          "EN-GJL-250 (sample)", "17-4 PH", application="Closed cooling-water circulation pump", equipment="CCW-P2 (fictitious)"),
        P("DES-3010", "Shaft spacer sleeve 60", "spacer_sleeve", dict(od=60, id_=42, length=48, chamfer=2), "DES-P02", "nopass",
          "AISI 316 (sample)", "SS 316L", application="Cooling-water pump shaft", status="draft"),
    ],
    admin=("Elena", "Demo-Admin"), user=("Tom", "Demo-User"),
)

CLIENTS = [MARITIME, INDUSTRIAL, ENERGY]
OPERATOR_STAFF = [("admin@operator.demo", "operator_admin", "Olivia", "Operator"),
                  ("engineer@operator.demo", "operator_engineer", "Ethan", "Engineer")]
