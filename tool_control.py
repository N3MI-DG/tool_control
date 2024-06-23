#!/usr/bin/python

import re
import math
import argparse

# Created by David Gray 2024

# Credits to Ankur Verma for original "detectMove" code
# https://github.com/ankurv2k6/daksh-toolchanger-v2/blob/main/PrusaSlicer/intelligent%20tool%20management/postprocess.py

slicer_vars = [
    "temperature",
    "min_fan_speed",
    "max_fan_speed",
    "layer_height",
    "full_fan_speed_layer",
    "first_layer_temperature",
    "first_layer_height",
    "fan_always_on",
    "disable_fan_first_layers",
]

temperature              = None
min_fan_speed            = None
max_fan_speed            = None
layer_height             = None
full_fan_speed_layer     = None
first_layer_temperature  = None
first_layer_height       = None
fan_always_on            = None
disable_fan_first_layers = None

print_start_line   = None
initial_tool       = None
layer_number       = 0
set_temps          = {}
gcode_temp_changes = {}
tool_numbers       = []
tool_changes       = []
matched_lines      = {}
inserted_lines     = []

currentFeedRate    = 0
currentX           = 0
currentY           = 0

interval           = 120
dock_interval      = 10
dock_delta         = 10

parser = argparse.ArgumentParser()
parser.add_argument("input_file",      type=str, help="GCode file to be processed")
parser.add_argument("--interval",      type=int, help="Inactive tool cool/heat interval in seconds")
parser.add_argument("--dock_interval", type=int, help="Time in seconds to preheat before tool change")
parser.add_argument("--dock_delta",    type=int, help="Temperature drop while docked")

args          = parser.parse_args()
file_input    = args.input_file
interval      = args.interval if args.interval else interval
dock_interval = args.dock_interval if args.dock_interval else dock_interval
dock_delta    = args.dock_delta if args.dock_delta else dock_delta


def detectToolChange(line, i, line_info):
    global initial_tool

    match = re.search(r'^(T(\d))$', line)

    if match is not None:
        tool_name                = match.group(1)
        tool_number              = int(tool_name[1])
        line_info['tool_change'] = tool_name

        tool_changes.append(i)

        if tool_number not in tool_numbers:
            tool_numbers.append(tool_number)

    return(line_info, bool(match))


def detectMove(line, i, line_info):
    global currentFeedRate, currentX, currentY

    deltaX = 0
    deltaY = 0
    match  = re.search(r'^G1(\s(X)(\d*\.*\d*))*(\s(Y)(\d*\.*\d*))*(\s(E)((-)*\d*\.*\d*))*(\s(F)(\d+\.*\d*))*', line)

    if match is not None:
        line_info['pos'] = i

        for grp in match.groups():
            if grp is not None:
                if len(grp) > 1:
                    m = re.search(r'(X|Y|E|F)(-*\d*\.*\d*)', grp)

                    if m:
                        line_info[m.group(1)] = m.group(2)

        if "F" in line_info:
            currentFeedRate = float(line_info['F'])

        if "X" in line_info:
            deltaX   = abs(float(line_info['X']) - currentX )
            currentX = float(line_info['X'])

        if "Y" in line_info:
            deltaY   = abs(float(line_info['Y']) - currentY)
            currentY = float(line_info['Y'])

        if deltaX > 0 or deltaY > 0:
            mmPerSecond   = currentFeedRate / 60
            segmentLength = math.sqrt(deltaX**2 + deltaY**2)
            move_time     = float(segmentLength / mmPerSecond)

            line_info['move_time'] = move_time

    return(line_info, bool(match))


def detectLayerChange(line, line_info):
    match  = re.search(r'^;Z:(\d+(?:\.\d+)?)', line)

    if match is not None:
        height = float(match.group(1))
        line_info['layer_height'] = height
    
    return(line_info, bool(match))


def detectTempChange(line, line_info):
    match  = re.search(r'^M104 S(\d+) T(\d)', line)

    if match:
        temp        = int(match.group(1))
        tool_number = int(match.group(2))
        
        line_info['temp_change'] = (temp, tool_number)
    
    return(line_info, bool(match))


def changeToolTemp(tool, f_index, status):
    global inserted_lines, set_temps

    if status == "cool":
        temp = 0
        msg  = f"Cooling T{tool} to {temp}"

    elif status == "dock_cool":
        current_temp = first_layer_temperature[tool] if layer_number == 1 else temperature[tool]
        temp         = current_temp - dock_delta
        msg          = f"Cooling T{tool} to {temp}"

    elif status in ["heat", "dock_heat"]:
        temp = first_layer_temperature[tool] if layer_number == 1 else temperature[tool]
        temp = temp-dock_delta if status == "heat" else temp
        msg  = f"Heating T{tool} to {temp}"

    set_temps[tool][f_index] = temp

    insert_gcodes = [
        f"RESPOND TYPE=echo MSG=\"{msg}\"",
        f"M104 S{temp} T{tool}"
    ]

    for i, new_line in enumerate(insert_gcodes):
        inserted_lines.append((f_index+1+i, f_index, new_line))


def changeFanSpeed(tool, f_index, status):
    global inserted_lines

    if layer_number > disable_fan_first_layers[tool]:
        if status == "dock_heat":
            if layer_number >= full_fan_speed_layer[tool]:
                fan_speed = max_fan_speed[tool]
            else:
                fan_speed = (max_fan_speed[tool]/(full_fan_speed_layer[tool]-disable_fan_first_layers[tool])) * (layer_number-disable_fan_first_layers[tool])

            fan_speed = int(255 * (fan_speed/100))

        else:

            fan_speed = 0

        insert_gcodes = [
            f"M106 S{fan_speed} T{tool}"
        ]

        for i, new_line in enumerate(insert_gcodes):
            inserted_lines.append((f_index+1+i, f_index, new_line))


def toolEnd(tool, f_index):
    insert_gcodes = [
        f"RESPOND TYPE=echo MSG=\"Turning off T{tool}\""
        f"M104 T{tool} S0",
        f"M106 T{tool} S0",
        f"SET_STEPPER_ENABLE STEPPER=extruder{tool if tool > 0 else ''} ENABLE=0"
    ]

    for i, new_line in enumerate(insert_gcodes):
        inserted_lines.append((f_index+1+i, f_index, new_line))


def preemptiveControl(line_info, i):
    tool_name          = line_info['tool_change']
    tool               = int(tool_name[1])
    this_tool_tcs      = [x for x in tool_changes if matched_lines[x]['tool_change'] == tool_name]
    this_prev_tc       = this_tool_tcs[-2] if len(this_tool_tcs) >= 2 else None 
    first_change_lines = None

    if interval > 0: # User wants to cool while tool is not required
        tc_after_this_prev = tool_changes[tool_changes.index(this_prev_tc)+1] if this_prev_tc else None

        ### POST FIRST CHANGE ###
        if this_prev_tc is not None:
            ### COOLING ###
            # Get the durations between the tool that was used after this tool was last used and now
            # to determine if we need to cool before this tool change.
            cool_lines = [x for x in matched_lines if x > tc_after_this_prev] if tc_after_this_prev is not None else []
            duration   = sum([matched_lines[line]['move_time'] for line in cool_lines if 'move_time' in matched_lines[line]])

            if duration > interval:
                changeToolTemp(tool, f_index=tc_after_this_prev+1, status="cool")

            ### HEATING ###
            # If duration between the tool change after this tools last used 
            # and now is greater than interval, preemptively heat this tool.
            heat_lines    = [x for x in matched_lines if x > this_prev_tc] if tc_after_this_prev is not None else []
            moves         = [(line, matched_lines[line]['move_time']) for line in heat_lines if 'move_time' in matched_lines[line]]
            move_duration = sum([x[1] for x in moves])
            heat_line     = None

            if move_duration > interval:
                time_heat = []

                for line, duration in reversed(moves):
                    if sum(time_heat) > interval:
                        heat_line = line
                        break

                    else:
                        time_heat.append(duration)
                        continue

            if heat_line is not None:
                changeToolTemp(tool, f_index=heat_line, status="heat")

        ### FIRST CHANGE ###
        elif tool is not initial_tool: 
            first_change_lines = [x for x in matched_lines if x > print_start_line]

            ### COOLING ###
            # Check how long it took for this tool to be needed
            # and turn heater off at print_start if longer than set interval.
            duration = sum([matched_lines[line]['move_time'] for line in first_change_lines if 'move_time' in matched_lines[line]])

            if duration > interval:
                changeToolTemp(tool, f_index=print_start_line+1+tool, status="cool")

            ### HEATING ###
            # Get durations between start of print and now 
            # to determine if we should heat at print_start.
            moves          = [(line, matched_lines[line]['move_time']) for line in first_change_lines if 'move_time' in matched_lines[line]]
            move_duration = sum([x[1] for x in moves])
            heat_line = None

            if move_duration > interval:
                time_heat = []

                for line, duration in reversed(moves):
                    if sum(time_heat) > interval:
                        heat_line = line
                        break

                    else:
                        time_heat.append(duration)
                        continue

            if heat_line is not None:
                changeToolTemp(tool, f_index=heat_line, status="heat")


    ### DOCKING ###
    if dock_delta > 0 and dock_interval > 0: # User wants to drop temp while docked for short period
        prev_tool_index = tool_changes[tool_changes.index(i)-1] if len(tool_changes) > 1 else None

        ### DOCK COOLING ###
        if prev_tool_index is not None: # Not the initial print
            # Cool down the previous tool just before tool change

            previous_tool = int(matched_lines[prev_tool_index]['tool_change'][1])
            changeToolTemp(previous_tool, f_index=i-1, status="dock_cool")

        if fan_always_on[tool] == 1:
            changeFanSpeed(previous_tool, f_index=i-1, status="dock_cool")

        ### DOCK HEATING ###
        # Preheat the tool back to its target temperature
        dock_heat_lines = [x for x in matched_lines if x > this_prev_tc] if this_prev_tc is not None else [x for x in matched_lines]
        moves           = [(line, matched_lines[line]['move_time']) for line in dock_heat_lines if 'move_time' in matched_lines[line]]
        move_duration   = sum([x[1] for x in moves])
        heat_line       = None

        if move_duration > dock_interval:
            time_heat = []

            for line, duration in reversed(moves):
                if sum(time_heat) > dock_interval:
                    heat_line = line
                    break

                else:
                    time_heat.append(duration)
                    continue
        
        else:
            input("Dock interval is too high, aborting.")
            exit()

        if heat_line is not None:
            changeToolTemp(tool, f_index=heat_line, status="dock_heat")
        
        if fan_always_on[tool] == 1:
            changeFanSpeed(tool, f_index=i+1, status="dock_heat")


def reactiveControl():
    for tool in tool_numbers:
        tool_name = f"T{tool}"

        # Turn off tools that are no longer required
        if tool_name not in matched_lines[tool_changes[-1]]['tool_change']:
            # The last tool should be handled by print_end macro

            for i in reversed(tool_changes):
                if tool_name == matched_lines[i]['tool_change']:
                    # This is the last time this tool was required
                    next_tc = tool_changes[tool_changes.index(i)+1]
                    toolEnd(tool, f_index=next_tc)

                    break


        if dock_delta > 0 and dock_interval > 0:
            # Make sure the tools are at their expected temps when the first layer temp change happens

            for line in gcode_temp_changes[tool]:
                temp             = gcode_temp_changes[tool][line]
                prev_set_temps   = [x for x in set_temps[tool] if x < line]
                
                if len(prev_set_temps):
                    prev_temp_line   = sorted(prev_set_temps)[-1]
                    prev_temp_change = [x[2] for x in inserted_lines if x[1] == prev_temp_line][-1]
                    prev_temp        = detectTempChange(prev_temp_change, {})[0]['temp_change'][0]
                    printing_tool    = data[[x for x in tool_changes if x < prev_temp_line][-1]].strip()

                    if prev_temp > 0:
                        if tool_name != printing_tool:
                            data[line] = f"M104 S{temp-dock_delta} {tool_name}\n"
                    
                    else:
                        data[line] = f"; Keep {tool_name} temp at 0\n"


def matchVar(var, line):
    match = re.search(r'^;\s('+var+r')\s=', line)

    return(bool(match))


def matchToolValues(line, var):
    return([float(x) if '.' in x else int(x) for x in re.findall(r'(\d+(?:\.\d+)?)', line)])


if __name__ == "__main__":
    with open(file_input, "r") as f:
        data = f.readlines()

    # Get the slicer variables we need
    print("Parsing PrusaSlicer variables\n")

    var_break = False

    for i, line in enumerate(reversed(data)):
        for var in slicer_vars:
            if matchVar(var, line):
                locals()[var] = matchToolValues(line, var)

                print(var, locals()[var])

                if var == slicer_vars[-1]:
                    var_break = True

        if var_break:
            break

    set_temps          = {i: {} for i, x in enumerate(temperature)}
    gcode_temp_changes = {i: {} for i, x in enumerate(temperature)}

    # Parse gcode
    print("\nParsing Gcode, please wait\n")

    for i, line in enumerate(data):
        line = line.strip()

        line_info = {}

        if print_start_line is not None:
            # Check for move line as they are most common

            line_info, is_move = detectMove(line, i, line_info)

            if is_move:
                matched_lines[i] = line_info

            else:
                line_info, is_tool_change = detectToolChange(line, i, line_info)

                if is_tool_change:
                    matched_lines[i] = line_info
                    preemptiveControl(line_info, i)

                else:
                    line_info, is_layer_change = detectLayerChange(line, line_info)

                    if is_layer_change:
                        layer_number += 1
                        current_layer_height = line_info['layer_height']
                        matched_lines[i]     = line_info

                    else:
                        # Handle temp change after firast layer
                        if dock_delta > 0 and dock_interval > 0:
                            line_info, is_temp_change = detectTempChange(line, line_info)

                            if is_temp_change:
                                temp    = line_info['temp_change'][0]
                                tool    = line_info['temp_change'][1]

                                gcode_temp_changes[tool][i] = temp

        else:
            # Look for the first tool change, as it is the initial tool and where the print starts

            line_info, is_tool_change = detectToolChange(line, i, line_info)
            matched_lines[i] = line_info

            if is_tool_change: # Initial Tool
                initial_tool     = int(line_info['tool_change'][1])
                print_start_line = i


    # After going through all gcode lines
    # go back though the toolchanges and determine when 
    # each tool is no longer required and turn them off
    reactiveControl()
 
    inserted_lines = sorted(inserted_lines, key=lambda x: x[0])

    for i, new_line in enumerate(inserted_lines):
        line = new_line[0]+i
        line_data = new_line[2]+"\n"

        print("------")
        print(line+1)
        print("------")
        print(line_data.strip())

        data.insert(line, line_data)

    # with open(file_input, "w") as f:
    with open(file_input, "w") as f:
        gcode = "".join(data)
        print("Writing file:", file_input)
        f.write(gcode)

    f.close()

