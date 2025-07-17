import os
import math
import dash
from dash import dcc, html
from dash.dependencies import Input, Output, State

##############################
Device Classes
##############################

class DieselGenerator:
    def __init__(self, name, max_power_kW,grid_eff=0.95):
        self.name = name
        self.max_power = max_power_kW
        self.grid_efficiency = grid_eff  # As per diagram

    def fuel_consumed(self, grid_kW, eff_kWh_per_L):
        # grid_kW is AFTER efficiency loss
        if eff_kWh_per_L > 0:
            # Fuel required for requested grid_kW output
            input_power = grid_kW / self.grid_efficiency
            return input_power / eff_kWh_per_L
        return 0.0

class MainPropulsionMotor:
    def __init__(self, name, max_power_kW,direct_eff:float=1.0, grid_eff: float=0.95, max_grid_kw: float |None=None ):
        self.name = name
        self.max_power = max_power_kW
        self.grid_efficiency =grid_eff # To grid
        self.direct_efficiency = direct_eff # Direct to assigned propeller
        self.max_grid_kw = max_grid_kw if max_grid_kw is not None else max_power_kW  # default: same as max_power

    def fuel_consumed(self, mechanical_kW, electrical_kW, eff_kWh_per_L):
        # mechanical_kW: direct mechanical to assigned propeller (100%)
        # electrical_kW: via grid (95% efficient)
        if eff_kWh_per_L > 0:
            # For mechanical output
            mech_fuel = mechanical_kW / self.direct_efficiency / eff_kWh_per_L
            # For electrical output (to grid)
            elec_fuel = (electrical_kW / self.grid_efficiency) / eff_kWh_per_L
            return mech_fuel + elec_fuel
        return 0.0

class SolarPower:
    def __init__(self, area_m2, eff):
        self.area = area_m2
        self.eff = eff

    def generate_power(self, irr_kW_m2):
        return self.area * self.eff * irr_kW_m2

class Battery:
    def __init__(self, capacity_kWh, min_soc_kWh, initial_soc_kWh=None,charge_eff=1.0, discharge_eff=1.0):
        self.capacity = capacity_kWh
        self.min_soc = min_soc_kWh
        self.soc = initial_soc_kWh if initial_soc_kWh is not None else 0.5 * capacity_kWh
        self.charge_eff = charge_eff    # 100% as per diagram
        self.discharge_eff = discharge_eff # 100% as per diagram

    def charge(self, surplus_kW):
        if surplus_kW <= 0:
            return 0.0
        free_cap = self.capacity - self.soc
        storable = surplus_kW * self.charge_eff
        stored = min(storable, free_cap)
        self.soc += stored
        return stored

    def discharge(self, needed_kW):
        if needed_kW <= 0:
            return 0.0
        available = self.soc - self.min_soc
        if available < 0:
            available = 0
        max_out = available * self.discharge_eff
        used = min(needed_kW, max_out)
        self.soc -= used / self.discharge_eff
        return used

##############################
48-Hour Simulation
##############################

def create_irr_schedule(sunrise, sunset, peak=1.0):
    hours = 48
    arr = [0.0] * hours
    dh = sunset - sunrise
    if dh > 0:
        for h in range(hours):
            mod_hour = h % 24
            if sunrise <= mod_hour < sunset:
                frac = (mod_hour - sunrise) / dh
                arr[h] = peak * math.sin(math.pi * frac)
    return arr

def run_sim_integration(
    battery,
    solar_obj,
    fuel_eta,          #  kWh / L  ->  {'m1':…, 'm2':…, 'dg1':…, 'dg2':…}
    path_eta,          #  path efficiencies editable in UI
    devices,
    usage_blocks,
    hotel_loads, 
    aux_loads, 
    prop_loads,
    irr_schedule
):
    # unpack path-efficiency dictionary once for speed/readability
    m_direct = path_eta['m_direct']      # Motor ➜ own prop (normally 1.0)
    m_grid   = path_eta['m_grid']        # Motor ➜ grid (0.95)
    cross    = path_eta['m_cross']       # Motor cross-feed (0.9025 default)
    dg_grid  = path_eta['dg_grid']       # DG  ➜ grid (0.95)
    g2p      = path_eta['grid_prop']     # Grid➜ prop (0.95)
    
    hours = 48
    hourly_data = []

    for hour in range(hours):
        block     = hour // 4                # 0 … 11
        # Loads fractions for this 4 h block
        hotel_load = hotel_loads[block]
        aux_load = aux_loads[block]
        prop_load = prop_loads[block]


        start_soc = battery.soc  # Battery SOC at start of hour
        irr       = irr_schedule[hour]
        solar_kW  = solar_obj.generate_power(irr)

        # 1. subtract solar from hotel › aux › prop
        used_h    = min(hotel_load, solar_kW)
        s_left    = solar_kW - used_h
        left_h    = hotel_load - used_h

        used_a    = min(aux_load, s_left)
        s_left    = s_left - used_a
        left_a    = aux_load - used_a

        used_p    = min(prop_load, s_left)
        s_left    = s_left - used_p          # solar left after all loads
        left_p    = prop_load - used_p

       
        

        # usage fractions for this 4 h block
        m1_frac   = usage_blocks['Motor1'][block]
        m2_frac   = usage_blocks['Motor2'][block]
        dg1_frac  = usage_blocks['DG1'  ][block]
        dg2_frac  = usage_blocks['DG2'  ][block]

        m1_on     = devices['Motor1']['is_on']
        m2_on     = devices['Motor2']['is_on']
        dg1_on    = devices['DG1'   ]['is_on']
        dg2_on    = devices['DG2'   ]['is_on']


        # Propulsion need split 50 / 50 
        need_p1   = prop_load * 0.5
        need_p2   = prop_load * 0.5

        m1_avail  = m1_frac * devices['Motor1']['max_power'] if m1_on else 0
        m2_avail  = m2_frac * devices['Motor2']['max_power'] if m2_on else 0

        # direct mechanical to own prop
        p1_from_m1 = min(need_p1, m1_avail * m_direct)
        p2_from_m2 = min(need_p2, m2_avail * m_direct)
        m1_avail  -= p1_from_m1 / m_direct
        m2_avail  -= p2_from_m2 / m_direct

        # cross-feed (motor → grid → other prop)
        p2_from_m1 = min(need_p2 - p2_from_m2, m1_avail * cross)
        m1_avail  -= p2_from_m1 / cross

        p1_from_m2 = min(need_p1 - p1_from_m1, m2_avail * cross)
        m2_avail  -= p1_from_m2 / cross

        p1_supplied = p1_from_m1 + p1_from_m2
        p2_supplied = p2_from_m2 + p2_from_m1

        rem_p1 = need_p1 - p1_supplied
        rem_p2 = need_p2 - p2_supplied
        grid_prop_demand = (rem_p1 + rem_p2) / g2p if (rem_p1 + rem_p2) > 0 else 0

        # grid producers (corrected)
        # Calculate raw input power to grid and corresponding output (after efficiency losses)

        # Motors
        m1_grid_out = max(min(m1_avail * m_grid, devices['Motor1']['obj'].max_grid_kw), 0)
        m1_grid_raw = m1_grid_out / m_grid if m_grid > 0 else 0

        m2_grid_out = max(min(m2_avail* m_grid, devices['Motor2']['obj'].max_grid_kw), 0)
        m2_grid_raw = m2_grid_out / m_grid if m_grid > 0 else 0

        # Diesel generators
        # Calculate max output from DGs to grid (after losses)
        dg1_grid_out = max(dg1_frac * devices['DG1']['max_power'], 0) if dg1_on else 0
        dg1_raw_input = dg1_grid_out / dg_grid if dg_grid > 0 else 0

        dg2_grid_out = max(dg2_frac * devices['DG2']['max_power'], 0) if dg2_on else 0
        dg2_raw_input = dg2_grid_out / dg_grid if dg_grid > 0 else 0


        # Total grid power available (after conversion losses)
        total_grid = m1_grid_out + m2_grid_out + dg1_grid_out + dg2_grid_out


        # allocate grid power Hotel/Aux first, then Propulsion
        need_HA = left_h + left_a
        used_HA = min(total_grid, need_HA)
        grid_left = total_grid - used_HA

        used_prop = min(grid_left, grid_prop_demand)
        unmet_grid = need_HA + grid_prop_demand - (used_HA + used_prop)

        batt_out = 0
        if unmet_grid > 0:
            batt_out  = battery.discharge(unmet_grid)
            unmet_grid -= batt_out

        #battery charging with any surplus grid + leftover solar
        surplus_grid = (grid_left - used_prop) + s_left
        charged = battery.charge(surplus_grid) if surplus_grid > 0 else 0.0
        #Calculate the excess supply 
        excess = max(0.0, surplus_grid - charged)

        #Fuel bookkeeping
        m1_fuel = m2_fuel = dg1_fuel = dg2_fuel = 0.0
        if m1_on:
            m1_fuel = devices['Motor1']['obj'].fuel_consumed(
                p1_from_m1 + p2_from_m1,  # mechanical output
                m1_grid_out,              # electrical input (before efficiency loss)
                fuel_eta['m1']
            )
        if m2_on:
            m2_fuel = devices['Motor2']['obj'].fuel_consumed(
                p2_from_m2 + p1_from_m2,
                m2_grid_out,
                fuel_eta['m2']
            )
        if dg1_on:
            dg1_fuel = devices['DG1']['obj'].fuel_consumed(
                dg1_grid_out,  # ⚠️ use output AFTER grid efficiency – since method expects it
                fuel_eta['dg1']
            )
        if dg2_on:
            dg2_fuel = devices['DG2']['obj'].fuel_consumed(
                dg2_grid_out,
                fuel_eta['dg2']
            )

        total_fuel = m1_fuel + m2_fuel + dg1_fuel + dg2_fuel

        # collect hour record
        hourly_data.append({
            'hour'            : hour,
            'solar_kW'        : solar_kW,
            'hotel_left'      : left_h,
            'aux_left'        : left_a,
            'prop_left'       : left_p,
            'prop1_supplied'  : p1_supplied,
            'prop2_supplied'  : p2_supplied,
            'fuel_used'       : total_fuel,
            'batt_out'        : batt_out,
            'charging_from_surplus': charged,
            'unmet_load'      : unmet_grid,
            'excess_energy'   : excess,
            'start_batt_soc'  : start_soc,
            'end_batt_soc'    : battery.soc,
            'device_outputs'  : [
                {'device_name':'Motor1','fuel_used':m1_fuel,'grid_out':m1_grid_out},   
                {'device_name':'Motor2','fuel_used':m2_fuel,'grid_out':m2_grid_out},   
                {'device_name':'DG1'  ,'fuel_used':dg1_fuel,'grid_out':dg1_grid_out},  
                {'device_name':'DG2'  ,'fuel_used':dg2_fuel,'grid_out':dg2_grid_out},
            ],
        })

    return hourly_data

##############################
# Dash App (UI)
##############################
app = dash.Dash(__name__)

def generate_usage_inputs(prefix: str, defaults: list[float]):
    """
    Return one html.Div that contains 12 label / input pairs laid out in a
    single row.  IDs stay exactly the same (e.g. 'hotel-b7', 'prop-b10', …).
    """
    cells = []
    for i in range(12):
        start = i * 4          # 0, 4, 8, …
        end   = start + 4      # 4, 8, 12, …
        cells.append(
            html.Div(
                [
                    html.Label(f"{start}-{end}h",
                               style={"fontSize": "0.8rem", "marginBottom": "2px"}),
                    dcc.Input(
                        id=f"{prefix}-b{i}",
                        value=defaults[i],
                        step=0.1,
                        type="number",
                        style={"width": "70px"}
                    ),
                ],
                style={"display": "flex",          # vertical stack
                       "flexDirection": "column",
                       "alignItems": "center"}
            )
        )

    # one wrapper Div arranges the 12 cells in a row
    return html.Div(
        children=cells,
        style={
            # comment either layout out if you don’t want CSS Grid
            "display": "grid",
            "gridTemplateColumns": "repeat(12, auto)",
            "columnGap": "4px",
            # fallback for browsers without grid support:
            # "display": "inline-block",
        }
    )

app.layout = html.Div([
    html.H1("Energy Balance Tool (48-Hour)"),
    html.Img(
        src='/assets/efficiencies_diagram.png',
        style={'width': '80%', 'maxWidth': '800px', 'margin': '20px auto', 'display': 'block'}
    ),
#  EFFICIENCY CONTROLS
    html.H2("Efficiencies"),
    html.Div(
            # grid with two columns: one for labels, one for inputs
            children=[
                html.Label("Max Motor 1 → Grid (kW):"),
                dcc.Input(id='m1-max-grid', type='number', value=1000, step=10, min=0),

                html.Label("Max Motor 2 → Grid (kW):"),
                dcc.Input(id='m2-max-grid', type='number', value=1000, step=10, min=0),

                html.Label("Motor → Prop (direct)"),
                dcc.Input(id='m-direct-eff', type='number', value=1.0, step=0.01, min=0, max=1),

                html.Label("Motor → Grid"),
                dcc.Input(id='m-grid-eff', type='number', value=0.95, step=0.01, min=0, max=1),

                html.Label("Motor Cross-feed (M1→P2 / M2→P1)"),
                dcc.Input(id='m-cross-eff', type='number', value=0.9025, step=0.0001, min=0, max=1),

                html.Label("Genset → Grid"),
                dcc.Input(id='dg-grid-eff', type='number', value=0.95, step=0.01, min=0, max=1),

                html.Label("Battery charge eff"),
                dcc.Input(id='batt-charge-eff', type='number', value=1.0, step=0.01, min=0, max=1),

                html.Label("Battery discharge eff"),
                dcc.Input(id='batt-discharge-eff', type='number', value=1.0, step=0.01, min=0, max=1),

                html.Label("Grid → Propeller"),
                dcc.Input(id='grid-prop-eff', type='number', value=0.95, step=0.01, min=0, max=1),
            ],
            style={
                'display': 'grid',
                'gridTemplateColumns': '200px 200px',
                'columnGap': '10px',
                'rowGap': '15px',
                'border': '1px solid #ccc',
                'padding': '10px',
                'margin': '10px'
            }
        ),


    dcc.Store(id='store-hourly'),

    dcc.Graph(id='battery-graph'),
    dcc.Graph(id='fuel-graph'),
    html.H3(id='total-fuel-text', style={'margin':'10px 0'}),
    html.Div(id='click-details', style={'border':'1px solid #ccc','padding':'10px','margin':'10px'}),

    html.H2("Battery"),
    html.Div([
        html.Label("Capacity (kWh):"),
        dcc.Input(id='batt-cap', type='number', value=5000),
        
        html.Label("Min SoC (kWh):"),
        dcc.Input(id='batt-min', type='number', value=500),
        
        html.Label("Initial SoC (kWh):"),
        dcc.Input(id='batt-init', type='number', value=4500),
        ], 
    style={'display': 'grid',
                'gridTemplateColumns': '200px 200px',
                'columnGap': '10px',
                'rowGap': '15px',
                'border': '1px solid #ccc',
                'padding': '10px',
                'margin': '10px'}),

    html.H2("Solar (Sinwave model)"),
    html.Div([
        html.Label("Area (m²):"),
        dcc.Input(id='solar-area', type='number', value=100),
        
        html.Label("Efficiency (kW/m²):"),
        dcc.Input(id='solar-eff', type='number', value=0.2),
        
        html.Label("Sunrise Hour:"),
        dcc.Input(id='sunrise', type='number', value=6),
        
        html.Label("Sunset Hour:"),
        dcc.Input(id='sunset', type='number', value=18),
    ], style={'display': 'grid',
                'gridTemplateColumns': '200px 200px',
                'columnGap': '10px',
                'rowGap': '15px',
                'border': '1px solid #ccc',
                'padding': '10px',
                'margin': '10px'}),

    html.H2("Motor1"),
    html.Div([
        html.Label("Max Power (kW):"),
        dcc.Input(id='m1-power', type='number', value=1000),
        
        html.Label("Eff (kWh/L):"),
        dcc.Input(id='m1-eff', type='number', value=4.5),
        
        dcc.Checklist(id='m1-on', options=[{'label':'Use M1','value':'on'}], value=['on']),
        
        html.Label("Usage (%):"),
        
        generate_usage_inputs('m1', [0.0, 0.0, 0.0, 0.0, 0.8, 0.8, 0.0, 0.8, 0.8, 0.8, 0.8, 0.0])
    ], style={'display': 'grid',
                'gridTemplateColumns': '200px 200px',
                'columnGap': '10px',
                'rowGap': '15px',
                'border': '1px solid #ccc',
                'padding': '10px',
                'margin': '10px'}),

    html.H2("Motor2"),
    html.Div([
        html.Label("Max Power (kW):"),
        dcc.Input(id='m2-power', type='number', value=1000),
        
        html.Label("Eff (kWh/L):"),
        dcc.Input(id='m2-eff', type='number', value=4.5),
        
        dcc.Checklist(id='m2-on', options=[{'label':'Use M2','value':'on'}], value=['on']),
        
        html.Label("Usage (%):"),
        
        generate_usage_inputs('m2', [0.0, 0.0, 0.0, 0.0, 0.8, 0.8, 0.0, 0.8, 0.8, 0.8, 0.8, 0.0])

    ], style={'display': 'grid',
                'gridTemplateColumns': '200px 200px',
                'columnGap': '10px',
                'rowGap': '15px',
                'border': '1px solid #ccc',
                'padding': '10px',
                'margin': '10px'}),

    html.H2("DG1"),
    html.Div([
        html.Label("Max Power (kW):"),
        dcc.Input(id='dg1-power', type='number', value=250),
        
        html.Label("Eff (kWh/L):"),
        dcc.Input(id='dg1-eff', type='number', value=4.5),
        
        dcc.Checklist(id='dg1-on', options=[{'label':'Use DG1','value':'on'}], value=['on']),
        
        html.Label("Usage (%):"),
        
        generate_usage_inputs('dg1', [0.0, 0.0, 0.0, 0.0, 0.8, 0.8, 0.0, 0.8, 0.8, 0.8, 0.8, 0.0])
    ], style={'display': 'grid',
                'gridTemplateColumns': '200px 200px',
                'columnGap': '10px',
                'rowGap': '15px',
                'border': '1px solid #ccc',
                'padding': '10px',
                'margin': '10px'}),

    html.H2("DG2"),
    html.Div([
        html.Label("Max Power (kW):"),
        dcc.Input(id='dg2-power', type='number', value=250),
        
        html.Label("Eff (kWh/L):"),
        dcc.Input(id='dg2-eff', type='number', value=4.5),
        
        dcc.Checklist(id='dg2-on', options=[{'label':'Use DG2','value':'on'}], value=['on']),
        
        html.Label("Usage (%):"),
        
        generate_usage_inputs('dg2', [0.0, 0.0, 0.0, 0.0, 0.8, 0.8, 0.0, 0.8, 0.8, 0.8, 0.8, 0.0])
    ], style={'display': 'grid',
                'gridTemplateColumns': '200px 200px',
                'columnGap': '10px',
                'rowGap': '15px',
                'border': '1px solid #ccc',
                'padding': '10px',
                'margin': '10px'}),

    html.H2("Loads per 4-hour block"),
    html.Div([
        html.H3("Hotel Loads (kW)"),
        generate_usage_inputs('hotel', [190]*12),

        html.H3("Aux Loads (kW)"),
        generate_usage_inputs('aux', [30]*12),

        html.H3("Prop Loads (kW)"),
        generate_usage_inputs('prop', [900]*12),
    ], style={'display': 'grid',
                'gridTemplateColumns': '200px 200px',
                'columnGap': '10px',
                'rowGap': '15px',
                'border': '1px solid #ccc',
                'padding': '10px',
                'margin': '10px'})
])
##############################
MAIN CALLBACK
##############################
@app.callback(
    [
        Output('battery-graph','figure'),
        Output('fuel-graph','figure'),
        Output('store-hourly','data'),
        Output('total-fuel-text', 'children')
    ],
    [
        # ----- static inputs -----
        Input('batt-cap','value'), Input('batt-min','value'), Input('batt-init','value'),
        Input('solar-area','value'), Input('solar-eff','value'),
        Input('sunrise','value'),   Input('sunset','value'),

        # ----- motor 1 -----
        Input('m1-on','value'),  Input('m1-power','value'),  Input('m1-eff','value'),
        *[Input(f'm1-b{i}','value') for i in range(12)],

        # ----- motor 2 -----
        Input('m2-on','value'),  Input('m2-power','value'),  Input('m2-eff','value'),
        *[Input(f'm2-b{i}','value') for i in range(12)],

        # ----- genset 1 -----
        Input('dg1-on','value'), Input('dg1-power','value'), Input('dg1-eff','value'),
        *[Input(f'dg1-b{i}','value') for i in range(12)],

        # ----- genset 2 -----
        Input('dg2-on','value'), Input('dg2-power','value'), Input('dg2-eff','value'),
        *[Input(f'dg2-b{i}','value') for i in range(12)],

        # ----- loads -----
        *[Input(f'hotel-b{i}','value') for i in range(12)],
        *[Input(f'aux-b{i}','value') for i in range(12)],
        *[Input(f'prop-b{i}','value') for i in range(12)],

        # ----- editable efficiencies -----
        Input('m-direct-eff','value'),
        Input('m-grid-eff','value'),
        Input('m-cross-eff','value'),
        Input('dg-grid-eff','value'),
        Input('batt-charge-eff','value'),
        Input('batt-discharge-eff','value'),
        Input('grid-prop-eff','value'),
        Input('m1-max-grid','value'),
        Input('m2-max-grid','value'),

    ])
def run_integration_calc(
    bc, bmin, binit,
    sarea, seff, srise, sset,

    # Motor-1 block
    m1on, m1p, m1eff,
    m1b0, m1b1, m1b2, m1b3, m1b4, m1b5, m1b6, m1b7, m1b8, m1b9, m1b10, m1b11,

    # Motor-2 block
    m2on, m2p, m2eff,
    m2b0, m2b1, m2b2, m2b3, m2b4, m2b5, m2b6, m2b7, m2b8, m2b9, m2b10, m2b11,

    # DG-1 block
    dg1on, dg1p, dg1eff,
    dg1b0, dg1b1, dg1b2, dg1b3, dg1b4, dg1b5, dg1b6, dg1b7, dg1b8, dg1b9, dg1b10, dg1b11,

    # DG-2 block
    dg2on, dg2p, dg2eff,
    dg2b0, dg2b1, dg2b2, dg2b3, dg2b4, dg2b5, dg2b6, dg2b7, dg2b8, dg2b9, dg2b10, dg2b11,

    # loads
    hotel_b0, hotel_b1, hotel_b2, hotel_b3, hotel_b4, hotel_b5, hotel_b6, hotel_b7, hotel_b8, hotel_b9, hotel_b10, hotel_b11,
    aux_b0, aux_b1, aux_b2, aux_b3, aux_b4, aux_b5, aux_b6, aux_b7, aux_b8, aux_b9, aux_b10, aux_b11,
    prop_b0, prop_b1, prop_b2, prop_b3, prop_b4, prop_b5, prop_b6, prop_b7, prop_b8, prop_b9, prop_b10, prop_b11,


    # editable efficiencies
    m_direct_eff, m_grid_eff, m_cross_eff,
    dg_grid_eff, batt_charge_eff, batt_discharge_eff, grid_prop_eff,

    # Motor-Grid_Max
    m1_max_grid, m2_max_grid,
):
    m1b = [m1b0, m1b1, m1b2, m1b3, m1b4, m1b5, m1b6, m1b7, m1b8, m1b9, m1b10, m1b11]
    m2b = [m2b0, m2b1, m2b2, m2b3, m2b4, m2b5, m2b6, m2b7, m2b8, m2b9, m2b10, m2b11]
    dg1b = [dg1b0, dg1b1, dg1b2, dg1b3, dg1b4, dg1b5, dg1b6, dg1b7, dg1b8, dg1b9, dg1b10, dg1b11]
    dg2b = [dg2b0, dg2b1, dg2b2, dg2b3, dg2b4, dg2b5, dg2b6, dg2b7, dg2b8, dg2b9, dg2b10, dg2b11]
    
    

    
    f = lambda v, d: float(v) if v not in (None,'') else d
    
    #Loads
    hotel_loads = [f(x,190) for x in [hotel_b0, hotel_b1, hotel_b2, hotel_b3, hotel_b4, hotel_b5, hotel_b6, hotel_b7, hotel_b8, hotel_b9, hotel_b10, hotel_b11]]
    aux_loads   = [f(x,30) for x in [aux_b0, aux_b1, aux_b2, aux_b3, aux_b4, aux_b5, aux_b6, aux_b7, aux_b8, aux_b9, aux_b10, aux_b11]]
    prop_loads  = [f(x,900) for x in [prop_b0, prop_b1, prop_b2, prop_b3, prop_b4, prop_b5, prop_b6, prop_b7, prop_b8, prop_b9, prop_b10, prop_b11]]

    # objects
    battery = Battery(
        f(bc,5000), f(bmin,500), f(binit,2500),
        charge_eff    = f(batt_charge_eff,1.0),
        discharge_eff = f(batt_discharge_eff,1.0)
    )
    solar   = SolarPower(f(sarea,100), f(seff,0.2))

    m1 = MainPropulsionMotor('M1', f(m1p,1000),
                             direct_eff=f(m_direct_eff,1.0),
                             grid_eff  =f(m_grid_eff,0.95),
                             max_grid_kw=f(m1_max_grid,1000))
    m2 = MainPropulsionMotor('M2', f(m2p,1000),
                             direct_eff=f(m_direct_eff,1.0),
                             grid_eff  =f(m_grid_eff,0.95),
                             max_grid_kw=f(m2_max_grid,1000))
    dg1= DieselGenerator('DG1', f(dg1p,250), grid_eff=f(dg_grid_eff,0.95))
    dg2= DieselGenerator('DG2', f(dg2p,250), grid_eff=f(dg_grid_eff,0.95))

    devices = {
        'Motor1': {'obj': m1, 'max_power': f(m1p,1000), 'is_on': 'on' in (m1on or [])},
        'Motor2': {'obj': m2, 'max_power': f(m2p,1000), 'is_on': 'on' in (m2on or [])},
        'DG1':    {'obj': dg1,'max_power': f(dg1p,250),  'is_on': 'on' in (dg1on or [])},
        'DG2':    {'obj': dg2,'max_power': f(dg2p,250),  'is_on': 'on' in (dg2on or [])},
    }

    usage = {
        'Motor1': [f(x,0) for x in m1b],
        'Motor2': [f(x,0) for x in m2b],
        'DG1':    [f(x,0) for x in dg1b],
        'DG2':    [f(x,0) for x in dg2b],
    }

    fuel_eta = {'m1':f(m1eff,4.5), 'm2':f(m2eff,4.5),
                'dg1':f(dg1eff,4.5),'dg2':f(dg2eff,4.5)}

    path_eta = {
        'm_direct' : f(m_direct_eff,1.0),
        'm_grid'   : f(m_grid_eff,0.95),
        'm_cross'  : f(m_cross_eff,0.9025),
        'dg_grid'  : f(dg_grid_eff,0.95),
        'grid_prop': f(grid_prop_eff,0.95),
    }
    irr = create_irr_schedule(f(srise,6), f(sset,18))

    hourly = run_sim_integration(
        battery, solar,
        fuel_eta,
        path_eta,
        devices,
        usage,
        hotel_loads,
        aux_loads,
        prop_loads,
        irr
    )

    # simple plotting 
    hrs   = [r['hour'] for r in hourly]
    soc   = [r['end_batt_soc'] for r in hourly]
    fuel  = [r['fuel_used']     for r in hourly]
    tot_f = sum(fuel)

    fig_batt = {'data':[{'x':hrs,'y':soc,'type':'line'}],
                'layout':{'title':'Battery SoC (kWh)','xaxis':{'title':'h'}}}
    fig_fuel = {'data':[{'x':hrs,'y':fuel,'type':'bar'}],
                'layout':{'title':'Fuel / hour (L)','xaxis':{'title':'h'}}}

    return fig_batt, fig_fuel, hourly, f"Total fuel 48 h: {tot_f:.2f} L"
##############################
CLICK CALLBACK
##############################
@app.callback(
    Output('click-details','children'),
    Input('battery-graph','clickData'),
    State('store-hourly','data')
)
def show_click_details(clickData, all_data):
    if not clickData or not all_data:
        return "Click on Battery SoC chart to see hour details."
    hr = clickData['points'][0]['x']
    if hr < 0 or hr >= len(all_data):
        return f"No data for hour {hr}"
    row = all_data[hr]
    lines = []
    lines.append(html.Div(
        f"Hour={hr}, "
        f"Start Battery SoC={row['start_batt_soc']:.1f} kWh, "
        f"End Battery SoC={row['end_batt_soc']:.1f} kWh, "
        f"Fuel={row['fuel_used']:.2f} L"
    ))
    lines.append(html.Div(
        f"Solar={row['solar_kW']:.1f}, "
        f"BatteryOut={row['batt_out']:.1f}"
    ))
    lines.append(html.Div(
        f"Hotel Left={row['hotel_left']:.1f}, "
        f"Aux Left={row['aux_left']:.1f}, "
        f"Prop Left={row['prop_left']:.1f}, "
        f"Prop1 supplied={row.get('prop1_supplied',0):.1f}, "
        f"Prop2 supplied={row.get('prop2_supplied',0):.1f}"
    ))
    lines.append(html.Div(
    f"Excess energy (batt full): {row.get('excess_energy', 0):.1f} kW,"
    f"Unmet={row['unmet_load']:.1f} kW "
    ))
    lines.append(html.Div("Devices:"))
    for dev in row['device_outputs']:
        # base message
        msg = f"{dev['device_name']}: fuel={dev['fuel_used']:.2f} L"
        # if grid_out was stored, show it too
        if 'grid_out' in dev:
            msg += f", grid={dev['grid_out']:.1f} kW"
        lines.append(html.Div(msg))

    return html.Div(lines)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
        
    )
