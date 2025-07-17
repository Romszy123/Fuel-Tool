
Integrated Energy Simulation Dashboard (48-Hour Simulation)

This project provides an interactive web-based dashboard using for simulating the energy system of a vessel or facility powered by a mix of diesel generators, propulsion motors, solar panels, and a battery bank. The simulation spans a 48-hour period in hourly steps and helps visualize fuel consumption and battery State of Charge (SoC) based on input parameters.

Features

- Battery Storage Simulation: Models charging and discharging with efficiency losses.
- Diesel Generators (DG1 & DG2): Fuel consumption based on user-defined usage patterns.
- Main Propulsion Motors (Motor1 & Motor2): Fuel use modeled with efficiency and 12 usage blocks.
- Solar Panel Generation: Based on area, efficiency, and custom sunrise/sunset times.
- Load Prioritization: Hotel → Auxiliary → Propulsion loads, using solar and battery energy.
- Dynamic Usage Inputs: Each energy source includes 12 block inputs covering 4 hours each.
- Efficiency Inputs: Efficiencies for each process can be defined aswell as the size of the PTO. 
- Graphical Output:
  - Battery SoC over 48 hours.
  - Hourly fuel consumption chart.
  - Detailed info display when clicking on the SoC chart.


Simulation Assumptions

- 48-hour duration broken into 12 blocks of 4 hours.
- Solar irradiance repeats daily using a sine wave between sunrise and sunset.
- Device Usage Fractions: Define power output as a fraction of rated max power in each block.
- Load Order: Solar energy is first used for Hotel, then Aux, then Propulsion.
- Unmet Loads: If all power sources (including battery) are insufficient, unmet demand is recorded.

 How to Use as local host:

1. Install requirements detailed in requirements.txt

2. Run the Script:
   
   Engine_usage_Tool_48h_with_efficiencies_amendable.py
   

3. Interact via Web Interface:
   - Modify values such as solar area, battery size, device efficiencies.
   - Enable or disable each generator or motor.
   - Set usage for each 4-hour block.
   - Visualizations update automatically.
   - Click the battery graph to view hourly details.

Use as deploy to Fly.io

1. Install fly dependencies
2. Navigate to folder containing .py file and Fly.fmol file.
3. 'fly deploy' in shell. 

 Output Explanation

- Battery SoC Graph: Shows the remaining battery charge each hour.
- Fuel Graph: Shows hourly fuel consumption across all generators/motors.
- Total Fuel Text: Summarizes 48-hour total consumption.
- Click Details Panel: Detailed readout for selected hour showing:
  - Device outputs
  - Solar input
  - Battery interaction
  - Load breakdown
  - Unmet energy demand

File Structure

- `app.py`: Main Dash app and simulation logic.
- `run_sim_integration()`: Core engine for 48-hour simulation.
- `create_irr_schedule()`: Simulates irradiance based on solar hours.
- `Battery`, `SolarPower`, `DieselGenerator`, `MainPropulsionMotor`: Device classes.

Notes

- Fuel consumption is calculated as `power / efficiency` per hour.
- Each hour's fuel is summed to give total 48-hour usage.
- The app layout is built dynamically using helper functions for cleaner input forms.

License

This tool is for educational and exploratory purposes. No warranty provided for commercial use.


Currently designed to be used on Fly.io as a webapp. Navigate to folder 




To run locally:

Replace:if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
        
    )

  With: if __name__ == "__main__":
    app.run(                       
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        debug=True                
    )
