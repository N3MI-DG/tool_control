### Tool Control
A PrusaSlicer post processing script that allows you to control toolhead temps and fans during multi tool prints.

***

#### Tools that are not required until later in the print will have their heaters turned off at start of print

This helps stop filament becoming liquid in the nozzle while waiting potentially hours before use.

#### Preemptively heats tools at a set interval (~120 seconds by default) before they are needed

This can be changed via the --interval argument.
```tool_control.py ./sample.gcode --interval=180```

#### Turns off docked tool heaters that are not required for set interval (~120 seconds by default)

This is also controlled via --interval argument.
```tool_control.py ./sample.gcode --interval=180```

#### Drops temperature for docked tools that are still heated in the dock by a set delta (10 degrees by default)

This can be changed via the --dock_delta argument.
```tool_control.py ./sample.gcode --dock_delta=20```

#### Preemptively reheats the tool by the delta they were dropped. This happens (~10 seconds by default) before tool change

This can be changed via the --dock_interval argument.
```tool_control.py ./sample.gcode --dock_interval=15```

#### Turns off print fans when docking (and turns them back on before printing)

This only works if `Keep fan always on` is checked in filament cooling settings

#### Turns off tool heater, fans and extruder motor if the tool is no longer required

No point keeping the tool heads active if they are not going to be used again.
Expects the tools extruder to be named `extruder`, `extruder1`, `extruder2`, etc.

***

Thanks to Ankur Verma for [his implimentation](https://github.com/ankurv2k6/daksh-toolchanger-v2/blob/main/PrusaSlicer/intelligent%20tool%20management/postprocess.py "Github Link") of preemptive heating on which the movement calculations are derived.
