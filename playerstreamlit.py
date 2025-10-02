import streamlit as st
import json
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import matplotlib.gridspec as gridspec
from matplotlib.patches import Rectangle
import os
from pathlib import Path
from collections import defaultdict

# Page config
st.set_page_config(page_title="Player Performance Analysis", layout="wide")

# Title
st.title("Eredivisie 2025/2026 Player Analysis")

# Resolve paths relative to this file so it works on Streamlit Cloud
BASE_DIR = Path(__file__).parent
match_folder = str((BASE_DIR / "MatchEvents").resolve())

def load_json_lenient(file_path: str):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        # Fallbacks for BOM, concatenated JSON, or NDJSON
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            raw = f.read()
        raw = raw.lstrip('\ufeff').strip()
        # Try as a single JSON with trimming to outermost braces
        try:
            return json.loads(raw)
        except Exception:
            pass
        start = raw.find('{')
        end = raw.rfind('}')
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(raw[start:end+1])
            except Exception:
                pass
        # Try NDJSON: one JSON object per line, collect into list under 'data'
        items = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                items.append(obj)
            except Exception:
                continue
        if items:
            return { 'data': items }
        raise

def parse_teams_from_filename(name: str):
    # Extract: date (8 digits), then everything up to 'SciSportsEvents' => "Home vs Away"
    try:
        base = name
        if base.lower().endswith('.json'):
            base = base[:-5]
        # Expect leading date and a space
        date_part = base[:8]
        if not date_part.isdigit():
            return None, None, None
        rest = base[8:].lstrip()
        lower_rest = rest.lower()
        marker = 'scisportsevents'
        idx = lower_rest.find(marker)
        if idx == -1:
            return None, None, date_part
        middle = rest[:idx].strip()
        # Now middle should be "Home vs Away" exactly once
        if ' vs ' in middle:
            home, away = middle.split(' vs ', 1)
            home = home.strip()
            away = away.strip()
            return home or None, away or None, date_part
        return None, None, date_part
    except Exception:
        return None, None, None

# Load all match files
all_events_data = []
file_names = []
match_folder = "MatchEvents"
if os.path.exists(match_folder):
    json_files = sorted([p for p in Path(match_folder).glob("*.json")])
    for p in json_files:
        try:
            events_data = load_json_lenient(str(p))
            if events_data:
                all_events_data.append(events_data)
                file_names.append(p.name)
        except Exception as e:
            st.warning(f"Failed to load {p.name}: {e}")
            continue
else:
    st.warning("MatchEvents folder not found")

# Main app
if all_events_data:
    with st.spinner("Analyzing player performance across all matches..."):
        # Collect all events from all matches
        all_events = []
        for events_data in all_events_data:
            events = events_data.get('data', []) if isinstance(events_data, dict) else []
            all_events.extend(events)

        # Function to find all shot events
        def find_shot_events(events):
            shot_events = []
            SHOT_LABELS = [128, 143, 144, 142]
            for event in events:
                is_shot = 'shot' in str(event.get('baseTypeName', '')).lower()
                event_labels = event.get('labels', []) or []
                has_shot_label = any(label in event_labels for label in SHOT_LABELS)
                if is_shot or has_shot_label:
                    shot_info = {
                        'team': event.get('teamName', 'Unknown'),
                        'player': event.get('playerName', 'Unknown'),
                        'xG': event.get('metrics', {}).get('xG', 0.0),
                        'PSxG': event.get('metrics', {}).get('PSxG', None),
                        'time': int((event.get('startTimeMs', 0) or 0) / 1000 / 60),
                        'partId': event.get('partId', 1)
                    }
                    shot_events.append(shot_info)
            return shot_events

        # Function to find all successful dribble events
        def find_dribble_events(events):
            dribble_events = []
            for event in events:
                # Check for successful dribble/carry events
                if (event.get('baseTypeId') == 3 and  # DRIBBLE
                    event.get('subTypeId') == 300 and  # CARRY
                    event.get('resultId') == 1):  # SUCCESSFUL
                    
                    dribble_info = {
                        'team': event.get('teamName', 'Unknown'),
                        'player': event.get('playerName', 'Unknown'),
                        'goal_progression': event.get('metrics', {}).get('goalProgression', 0.0),
                        'time': int((event.get('startTimeMs', 0) or 0) / 1000 / 60),
                        'partId': event.get('partId', 1)
                    }
                    dribble_events.append(dribble_info)
            return dribble_events

        # Function to find progressive carry events (carry events with label 119)
        def find_progressive_carry_events(events):
            prog_carry_events = []
            for event in events:
                if event.get('baseTypeId') == 3 and event.get('subTypeId') == 300 and event.get('resultId') == 1:
                    labels = event.get('labels', []) or []
                    if 119 in labels:
                        prog_carry_events.append({
                            'team': event.get('teamName', 'Unknown'),
                            'player': event.get('playerName', 'Unknown'),
                            'time': int((event.get('startTimeMs', 0) or 0) / 1000 / 60),
                            'partId': event.get('partId', 1)
                        })
            return prog_carry_events

        # Function to find all take-on events (both successful and unsuccessful)
        def find_takeon_events(events):
            takeon_events = []
            for event in events:
                # Check for take-on events (label 120) and successful take-ons (label 121)
                event_labels = event.get('labels', []) or []
                if 120 in event_labels:  # TAKE_ON
                    is_successful = 121 in event_labels  # TAKE_ON_SUCCESS
                    takeon_info = {
                        'team': event.get('teamName', 'Unknown'),
                        'player': event.get('playerName', 'Unknown'),
                        'is_successful': is_successful,
                        'time': int((event.get('startTimeMs', 0) or 0) / 1000 / 60),
                        'partId': event.get('partId', 1)
                    }
                    takeon_events.append(takeon_info)
            return takeon_events

        # Function to find successful passes to box
        def find_passes_to_box_events(events):
            pass_events = []
            for event in events:
                # Check for successful passes to box (label 72)
                event_labels = event.get('labels', []) or []
                if 72 in event_labels:  # DEEP_COMPLETION_SUCCESS
                    pass_info = {
                        'team': event.get('teamName', 'Unknown'),
                        'player': event.get('playerName', 'Unknown'),
                        'time': int((event.get('startTimeMs', 0) or 0) / 1000 / 60),
                        'partId': event.get('partId', 1)
                    }
                    pass_events.append(pass_info)
            return pass_events

        # Function to find all successful pass events with goal progression and xA/labels
        def find_all_pass_events(events):
            all_passes = []
            for event in events:
                # Heuristic: baseTypeName contains 'pass' or baseTypeId == 2 (commonly used for passes)
                base_name = str(event.get('baseTypeName', '')).lower()
                if (('pass' in base_name) or (event.get('baseTypeId') == 2)) and event.get('resultId') == 1:
                    gp = event.get('metrics', {}).get('goalProgression', None)
                    xa = event.get('metrics', {}).get('xA', 0.0)
                    labels = event.get('labels', []) or []
                    all_passes.append({
                        'team': event.get('teamName', 'Unknown'),
                        'player': event.get('playerName', 'Unknown'),
                        'goal_progression': gp,
                        'xA': xa,
                        'labels': labels,
                        'time': int((event.get('startTimeMs', 0) or 0) / 1000 / 60),
                        'partId': event.get('partId', 1)
                    })
            return all_passes

        # Function to find counter pressure events
        def find_counter_pressure_events(events):
            pressure_events = []
            for event in events:
                # Check for counter pressure events (label 215)
                event_labels = event.get('labels', []) or []
                if 215 in event_labels:  # PRESSURE_ZONE_HIGH
                    pressure_info = {
                        'team': event.get('teamName', 'Unknown'),
                        'player': event.get('playerName', 'Unknown'),
                        'time': int((event.get('startTimeMs', 0) or 0) / 1000 / 60),
                        'partId': event.get('partId', 1)
                    }
                    pressure_events.append(pressure_info)
            return pressure_events

        # Function to find all goalkeeper events (saves and unsuccessful saves)
        def find_goalkeeper_events(events):
            gk_events = []
            for event in events:
                # Check for save events (baseTypeId 12)
                if event.get('baseTypeId') == 12:  # KEEPER_SAVE
                    gk_name = event.get('playerName', 'Unknown')
                    if gk_name and gk_name != 'Unknown':
                        result_id = event.get('resultId', 1)
                        is_successful = result_id == 1  # 1 = SUCCESSFUL
                        is_unsuccessful = result_id == 0  # 0 = UNSUCCESSFUL (only this counts as goal allowed)
                        # resultId == 3 means penalty wide/over goal, not a goal allowed
                        
                        save_info = {
                            'team': event.get('teamName', 'Unknown'),
                            'goalkeeper': gk_name,
                            'xs': event.get('metrics', {}).get('xS', 0.0),
                            'psxg': event.get('metrics', {}).get('PSxG', 0.0),
                            'is_save': is_successful,
                            'is_unsuccessful_save': is_unsuccessful,
                            'time': int((event.get('startTimeMs', 0) or 0) / 1000 / 60),
                            'partId': event.get('partId', 1),
                            'eventId': event.get('eventId', 'Unknown')
                        }
                        gk_events.append(save_info)
                
            return gk_events

        # Get all shot events, dribble events, take-on events, passes to box, counter pressures, and goalkeeper events
        all_shots = find_shot_events(all_events)
        all_dribbles = find_dribble_events(all_events)
        all_progressive_carries = find_progressive_carry_events(all_events)
        all_takeons = find_takeon_events(all_events)
        all_passes_to_box = find_passes_to_box_events(all_events)
        all_passes = find_all_pass_events(all_events)
        all_counter_pressures = find_counter_pressure_events(all_events)
        all_gk_events = find_goalkeeper_events(all_events)
        
        # Additional event collections by baseType/subType/resultId
        def find_successful_label_events(events, label_set):
            found = []
            for event in events:
                if event.get('resultId') == 1:
                    labels = event.get('labels', []) or []
                    if any(l in labels for l in label_set):
                        found.append({
                            'team': event.get('teamName', 'Unknown'),
                            'player': event.get('playerName', 'Unknown'),
                            'time': int((event.get('startTimeMs', 0) or 0) / 1000 / 60),
                            'partId': event.get('partId', 1)
                        })
            return found

        def find_events_by_type_subtype(events, base_type, sub_type, result_id=None):
            found = []
            for event in events:
                if (event.get('baseTypeId') == base_type and
                    event.get('subTypeId') == sub_type and
                    (result_id is None or event.get('resultId') == result_id)):
                    found.append({
                        'team': event.get('teamName', 'Unknown'),
                        'player': event.get('playerName', 'Unknown'),
                        'time': int((event.get('startTimeMs', 0) or 0) / 1000 / 60),
                        'partId': event.get('partId', 1)
                    })
            return found

        successful_counter_pressure_labels = {214, 215, 216}
        successful_pressure_labels = {213}

        all_successful_counter_pressures = find_successful_label_events(all_events, successful_counter_pressure_labels)
        all_successful_pressures = find_successful_label_events(all_events, successful_pressure_labels)
        # Air duels: baseType 4, subType 402 (any result)
        all_air_duel_totals = find_events_by_type_subtype(all_events, 4, 402)
        all_air_duel_wins = find_events_by_type_subtype(all_events, 4, 402, 1)
        # Tackles: baseType 4, subType 400 (any result)
        all_tackle_totals = find_events_by_type_subtype(all_events, 4, 400)
        all_successful_tackles = find_events_by_type_subtype(all_events, 4, 400, 1)
        # Interceptions: baseType 5, subType 500 (any result)
        all_interception_totals = find_events_by_type_subtype(all_events, 5, 500)
        all_successful_interceptions = find_events_by_type_subtype(all_events, 5, 500, 1)
        
        # Create a mapping of events to their source files
        events_to_file = {}
        for file_idx, events_data in enumerate(all_events_data):
            events = events_data.get('data', []) if isinstance(events_data, dict) else []
            for event in events:
                # Create a unique key for each event
                event_key = f"{event.get('baseTypeId')}_{event.get('playerName')}_{event.get('startTimeMs')}_{event.get('partId')}"
                events_to_file[event_key] = file_idx
        
        # Calculate player minutes played
        def calculate_player_minutes(events):
            """Calculate minutes played for each player based on substitutions and periods"""
            player_minutes = {}
            period_starts = {}
            period_ends = {}
            substitutions = {}
            
            # Find period start/end times
            for event in events:
                if event.get('baseTypeId') == 14:  # Period events
                    part_id = event.get('partId', 1)
                    time_ms = event.get('startTimeMs', 0)
                    time_minutes = time_ms / 1000 / 60 if time_ms else 0
                    
                    if event.get('subTypeId') == 1400:  # Period start
                        period_starts[part_id] = time_minutes
                    elif event.get('subTypeId') == 1401:  # Period end
                        period_ends[part_id] = time_minutes
            
            # Find substitutions
            for event in events:
                if event.get('baseTypeId') == 16:  # Substitution
                    player_name = event.get('playerName', '')
                    time_ms = event.get('startTimeMs', 0)
                    time_minutes = time_ms / 1000 / 60 if time_ms else 0
                    part_id = event.get('partId', 1)
                    
                    if event.get('subTypeId') == 1601:  # Subbed in
                        if player_name not in substitutions:
                            substitutions[player_name] = []
                        substitutions[player_name].append({
                            'type': 'in',
                            'time': time_minutes,
                            'part_id': part_id
                        })
                    elif event.get('subTypeId') == 1600:  # Subbed out
                        if player_name not in substitutions:
                            substitutions[player_name] = []
                        substitutions[player_name].append({
                            'type': 'out',
                            'time': time_minutes,
                            'part_id': part_id
                        })
            
            # Find red cards
            red_cards = {}
            for event in events:
                if event.get('baseTypeId') == 15:  # Card events
                    if event.get('subTypeId') in [1501, 1502]:  # Red card
                        player_name = event.get('playerName', '')
                        time_ms = event.get('startTimeMs', 0)
                        time_minutes = time_ms / 1000 / 60 if time_ms else 0
                        part_id = event.get('partId', 1)
                        red_cards[player_name] = {
                            'time': time_minutes,
                            'part_id': part_id
                        }
            
            # Calculate minutes for each player
            all_players = set()
            for event in events:
                player_name = event.get('playerName', '')
                if player_name:
                    all_players.add(player_name)
            
            for player_name in all_players:
                total_minutes = 0
                
                # Get player's substitution events
                player_subs = substitutions.get(player_name, [])
                
                # Sort by time
                player_subs.sort(key=lambda x: x['time'])
                
                # Determine start and end times for each period
                for part_id in [1, 2]:
                    period_start = period_starts.get(part_id, 0 if part_id == 1 else 45)
                    period_end = period_ends.get(part_id, 45 if part_id == 1 else 90)
                    
                    # Find when player entered this period
                    player_entered = None
                    for sub in player_subs:
                        if sub['part_id'] == part_id and sub['type'] == 'in':
                            player_entered = sub['time']
                            break
                    
                    # If not subbed in, assume they started the period
                    if player_entered is None:
                        player_entered = period_start
                    
                    # Find when player left this period
                    player_left = None
                    
                    # Check for substitution out
                    for sub in player_subs:
                        if sub['part_id'] == part_id and sub['type'] == 'out' and sub['time'] > player_entered:
                            player_left = sub['time']
                            break
                    
                    # Check for red card
                    if player_name in red_cards:
                        red_card = red_cards[player_name]
                        if red_card['part_id'] == part_id and red_card['time'] > player_entered:
                            if player_left is None or red_card['time'] < player_left:
                                player_left = red_card['time']
                    
                    # If no exit event, player played until end of period
                    if player_left is None:
                        player_left = period_end
                    
                    # Add minutes for this period
                    if player_entered < player_left:
                        total_minutes += player_left - player_entered
                
                player_minutes[player_name] = total_minutes
            
            return player_minutes
        
        # Position mapping to Dutch, more general positions
        POSITION_MAP_NL = {
            'GK': 'DM',
            'LB': 'LV',
            'LWB': 'LVV',
            'LCB': 'CV',
            'CB': 'CV',
            'RCB': 'CV',
            'RWB': 'RVV',
            'RB': 'RV',
            'LDMF': 'VM',
            'DMF': 'VM',
            'RDMF': 'VM',
            'LCMF': 'CM',
            'CMF': 'CM',
            'RCMF': 'CM',
            'LCM': 'CM',
            'CM': 'CM',
            'RCM': 'CM',
            'LW': 'LB',
            'RW': 'RB',
            'LWF': 'LB',
            'RWF': 'RB',
            'LAMF': 'LB',
            'RAMF': 'RB',
            'AMF': 'AM',
            'LCF': 'SP',
            'RCF': 'SP',
            'CF': 'SP',
            'RM': 'RM',
            'LM': 'LM'
        }

        def map_position_to_nl(raw_position_name: str):
            if not raw_position_name:
                return raw_position_name
            key = str(raw_position_name).strip().upper()
            return POSITION_MAP_NL.get(key, raw_position_name)

        # Calculate players' primary positions across the entire season (with position mapping)
        def calculate_primary_positions_across_matches(all_matches_events):
            """Aggregate position durations per player name across all matches and return primary position per player.
            Uses POSITION events (baseTypeId 18 with subTypeId 1800/1801) and closes stints on period end events (baseTypeId 14, subTypeId 1401).
            """
            POSITION_BASE_TYPE = 18
            PLAYER_DETAILED_POSITION_SUBTYPE = 1800
            PLAYER_POSITION_CHANGE_SUBTYPE = 1801
            PERIOD_END_BASE_TYPE = 14
            PERIOD_START_SUBTYPE = 1400
            PERIOD_END_SUBTYPE = 1401
            SUBSTITUTION_BASE_TYPE = 16
            SUB_OUT_SUBTYPE = 1600
            SUB_IN_SUBTYPE = 1601

            player_position_durations_ms = defaultdict(lambda: defaultdict(int))

            for events_data in all_matches_events:
                events = events_data.get('data', []) if isinstance(events_data, dict) else []
                # Keep only position updates, period start/end markers, and substitutions
                position_and_period_events = [
                    e for e in events
                    if (e.get('baseTypeId') == POSITION_BASE_TYPE and e.get('subTypeId') in (PLAYER_DETAILED_POSITION_SUBTYPE, PLAYER_POSITION_CHANGE_SUBTYPE))
                    or (e.get('baseTypeId') == PERIOD_END_BASE_TYPE and e.get('subTypeId') in (PERIOD_START_SUBTYPE, PERIOD_END_SUBTYPE))
                    or (e.get('baseTypeId') == SUBSTITUTION_BASE_TYPE and e.get('subTypeId') in (SUB_OUT_SUBTYPE, SUB_IN_SUBTYPE))
                ]
                position_and_period_events.sort(key=lambda x: x.get('startTimeMs', 0) or 0)

                # Map of player -> { 'position_name': str, 'start_time': int or None }
                # start_time None means carried over across period boundary awaiting next period start
                current_player_position = {}

                for e in position_and_period_events:
                    event_time_ms = e.get('startTimeMs', 0) or 0
                    base_type_id = e.get('baseTypeId')
                    sub_type_id = e.get('subTypeId')

                    # Handle position updates
                    if base_type_id == POSITION_BASE_TYPE and sub_type_id in (PLAYER_DETAILED_POSITION_SUBTYPE, PLAYER_POSITION_CHANGE_SUBTYPE):
                        player_name = e.get('playerName')
                        position_type_name = e.get('positionTypeName')
                        if player_name and player_name != 'NOT_APPLICABLE' and player_name != 'Unknown' and player_name.strip() and position_type_name and position_type_name != 'UNKNOWN':
                            mapped_position = map_position_to_nl(position_type_name)
                            if player_name in current_player_position:
                                prev = current_player_position[player_name]
                                # Only add if stint was active
                                if prev.get('start_time') is not None:
                                    duration = event_time_ms - prev['start_time']
                                    if duration > 0:
                                        player_position_durations_ms[player_name][prev['position_name']] += duration
                            current_player_position[player_name] = {
                                'position_name': mapped_position,
                                'start_time': event_time_ms
                            }

                    # Period start: resume stints for players carried over (start_time is None)
                    if base_type_id == PERIOD_END_BASE_TYPE and sub_type_id == PERIOD_START_SUBTYPE:
                        for pname, pos_info in current_player_position.items():
                            if pos_info.get('start_time') is None:
                                pos_info['start_time'] = event_time_ms

                    # Period end: close all active stints, but carry positions to next period (start_time becomes None)
                    if base_type_id == PERIOD_END_BASE_TYPE and sub_type_id == PERIOD_END_SUBTYPE:
                        for pname, pos_info in current_player_position.items():
                            if pos_info.get('start_time') is not None:
                                duration = event_time_ms - pos_info['start_time']
                                if duration > 0:
                                    player_position_durations_ms[pname][pos_info['position_name']] += duration
                                # Mark as carried over across break
                                pos_info['start_time'] = None

                    # Substitutions: close stint on sub out; ignore sub in until position event occurs
                    if base_type_id == SUBSTITUTION_BASE_TYPE and sub_type_id == SUB_OUT_SUBTYPE:
                        player_name = e.get('playerName')
                        if player_name and player_name in current_player_position:
                            pos_info = current_player_position[player_name]
                            if pos_info.get('start_time') is not None:
                                duration = event_time_ms - pos_info['start_time']
                                if duration > 0:
                                    player_position_durations_ms[player_name][pos_info['position_name']] += duration
                            # Remove player from field
                            del current_player_position[player_name]

                # Close any remaining open stints at the final event time in this match
                if position_and_period_events:
                    final_event_time_ms = position_and_period_events[-1].get('startTimeMs', 0) or 0
                    for pname, pos_info in list(current_player_position.items()):
                        if pos_info.get('start_time') is not None:
                            duration = final_event_time_ms - pos_info['start_time']
                            if duration > 0:
                                player_position_durations_ms[pname][pos_info['position_name']] += duration
                    current_player_position.clear()

            # Determine primary (most-played) position for each player
            primary_position_by_player = {}
            for pname, pos_map in player_position_durations_ms.items():
                if pos_map:
                    primary_position_by_player[pname] = max(pos_map.items(), key=lambda kv: kv[1])[0]
                else:
                    primary_position_by_player[pname] = 'N/A'

            return primary_position_by_player, player_position_durations_ms
        
        # Calculate minutes played for all players across all matches
        total_player_minutes = {}
        
        # Process each match separately and sum up minutes
        for events_data in all_events_data:
            events = events_data.get('data', []) if isinstance(events_data, dict) else []
            match_minutes = calculate_player_minutes(events)
            
            # Add to total minutes for each player
            for player_name, minutes in match_minutes.items():
                if player_name not in total_player_minutes:
                    total_player_minutes[player_name] = 0
                total_player_minutes[player_name] += minutes
        
        # Calculate player statistics
        player_stats = {}

        # Pre-compute primary positions across the whole season
        primary_positions_by_player, _position_duration_ms = calculate_primary_positions_across_matches(all_events_data)

        # Summarize minutes for primary, second, and third positions per player
        def summarize_position_minutes(position_duration_ms):
            summaries = {}
            for pname, pos_map in position_duration_ms.items():
                # Sort by duration descending
                sorted_items = sorted(pos_map.items(), key=lambda kv: kv[1], reverse=True)
                primary_minutes = (sorted_items[0][1] / 60000.0) if len(sorted_items) >= 1 else 0.0
                second_name = sorted_items[1][0] if len(sorted_items) >= 2 else None
                third_name = sorted_items[2][0] if len(sorted_items) >= 3 else None
                secondary_positions = " / ".join([p for p in [second_name, third_name] if p])
                secondary_minutes = 0.0
                if len(sorted_items) >= 2:
                    secondary_minutes += sorted_items[1][1] / 60000.0
                if len(sorted_items) >= 3:
                    secondary_minutes += sorted_items[2][1] / 60000.0
                summaries[pname] = {
                    'primary_minutes': primary_minutes,
                    'secondary_positions': secondary_positions,
                    'secondary_minutes': secondary_minutes
                }
            return summaries

        position_minutes_summary = summarize_position_minutes(_position_duration_ms)
        
        # Process shots
        for shot in all_shots:
            player_name = shot['player']
            if player_name not in player_stats:
                player_stats[player_name] = {
                    'team': shot['team'],
                    'xG': 0.0,
                    'xA': 0.0,
                    'PSxG': 0.0,
                    'shots': 0,
                    'pbd': 0.0,
                    'pbp': 0.0,
                    'takeons': 0,
                    'takeons_total': 0,
                    'passes_to_box': 0,
                    'keypasses': 0,
                    'counter_pressures': 0,
                    'progressive_carries': 0,
                    'progressive_passes': 0,
                    'goals_prevented': 0.0,
                    'psxg_faced': 0.0,
                    'goals_allowed': 0,
                    'minutes_played': total_player_minutes.get(player_name, 0),
                    'position': primary_positions_by_player.get(player_name, 'N/A'),
                    'primary_position_minutes': position_minutes_summary.get(player_name, {}).get('primary_minutes', 0.0),
                    'secondary_positions': position_minutes_summary.get(player_name, {}).get('secondary_positions', ''),
                    'secondary_positions_minutes': position_minutes_summary.get(player_name, {}).get('secondary_minutes', 0.0)
                }
            
            player_stats[player_name]['xG'] += shot['xG']
            player_stats[player_name]['shots'] += 1
            if shot['PSxG'] is not None:
                player_stats[player_name]['PSxG'] += shot['PSxG']
        
        # Process dribbles for PBD calculation
        for dribble in all_dribbles:
            player_name = dribble['player']
            if player_name not in player_stats:
                player_stats[player_name] = {
                    'team': dribble['team'],
                    'xG': 0.0,
                    'xA': 0.0,
                    'PSxG': 0.0,
                    'shots': 0,
                    'pbd': 0.0,
                    'pbp': 0.0,
                    'takeons': 0,
                    'takeons_total': 0,
                    'passes_to_box': 0,
                    'keypasses': 0,
                    'counter_pressures': 0,
                    'progressive_carries': 0,
                    'progressive_passes': 0,
                    'goals_prevented': 0.0,
                    'psxg_faced': 0.0,
                    'goals_allowed': 0,
                    'minutes_played': total_player_minutes.get(player_name, 0),
                    'position': primary_positions_by_player.get(player_name, 'N/A'),
                    'primary_position_minutes': position_minutes_summary.get(player_name, {}).get('primary_minutes', 0.0),
                    'secondary_positions': position_minutes_summary.get(player_name, {}).get('secondary_positions', ''),
                    'secondary_positions_minutes': position_minutes_summary.get(player_name, {}).get('secondary_minutes', 0.0)
                }
            
            # Add goal progression (negative means closer to goal, so we add the negative value)
            goal_progression = dribble['goal_progression']
            if goal_progression < 0:  # Negative means progression toward goal
                player_stats[player_name]['pbd'] += abs(goal_progression)
        
        # Process take-ons for successful and total take-on count
        for takeon in all_takeons:
            player_name = takeon['player']
            if player_name not in player_stats:
                player_stats[player_name] = {
                    'team': takeon['team'],
                    'xG': 0.0,
                    'xA': 0.0,
                    'PSxG': 0.0,
                    'shots': 0,
                    'pbd': 0.0,
                    'pbp': 0.0,
                    'takeons': 0,
                    'takeons_total': 0,
                    'passes_to_box': 0,
                    'keypasses': 0,
                    'counter_pressures': 0,
                    'progressive_carries': 0,
                    'progressive_passes': 0,
                    'goals_prevented': 0.0,
                    'psxg_faced': 0.0,
                    'goals_allowed': 0,
                    'minutes_played': total_player_minutes.get(player_name, 0),
                    'position': primary_positions_by_player.get(player_name, 'N/A'),
                    'primary_position_minutes': position_minutes_summary.get(player_name, {}).get('primary_minutes', 0.0),
                    'secondary_positions': position_minutes_summary.get(player_name, {}).get('secondary_positions', ''),
                    'secondary_positions_minutes': position_minutes_summary.get(player_name, {}).get('secondary_minutes', 0.0)
                }
            
            # Count total take-ons
            player_stats[player_name]['takeons_total'] += 1
            
            # Count successful take-ons
            if takeon['is_successful']:
                player_stats[player_name]['takeons'] += 1
        
        # Process passes to box
        for pass_event in all_passes_to_box:
            player_name = pass_event['player']
            if player_name not in player_stats:
                player_stats[player_name] = {
                    'team': pass_event['team'],
                    'xG': 0.0,
                    'xA': 0.0,
                    'PSxG': 0.0,
                    'shots': 0,
                    'pbd': 0.0,
                    'pbp': 0.0,
                    'takeons': 0,
                    'takeons_total': 0,
                    'passes_to_box': 0,
                    'keypasses': 0,
                    'counter_pressures': 0,
                    'progressive_carries': 0,
                    'progressive_passes': 0,
                    'goals_prevented': 0.0,
                    'psxg_faced': 0.0,
                    'goals_allowed': 0,
                    'minutes_played': total_player_minutes.get(player_name, 0),
                    'position': primary_positions_by_player.get(player_name, 'N/A'),
                    'primary_position_minutes': position_minutes_summary.get(player_name, {}).get('primary_minutes', 0.0),
                    'secondary_positions': position_minutes_summary.get(player_name, {}).get('secondary_positions', ''),
                    'secondary_positions_minutes': position_minutes_summary.get(player_name, {}).get('secondary_minutes', 0.0)
                }
            
            # Count successful passes to box
            player_stats[player_name]['passes_to_box'] += 1
        
        # Process counter pressures (all occurrences) and successful variants
        for pressure_event in all_counter_pressures:
            player_name = pressure_event['player']
            if player_name not in player_stats:
                player_stats[player_name] = {
                    'team': pressure_event['team'],
                    'xG': 0.0,
                    'xA': 0.0,
                    'PSxG': 0.0,
                    'shots': 0,
                    'pbd': 0.0,
                    'pbp': 0.0,
                    'takeons': 0,
                    'takeons_total': 0,
                    'passes_to_box': 0,
                    'keypasses': 0,
                    'counter_pressures': 0,
                    'successful_counter_pressures': 0,
                    'successful_pressures': 0,
                    'progressive_carries': 0,
                    'progressive_passes': 0,
                    'goals_prevented': 0.0,
                    'psxg_faced': 0.0,
                    'goals_allowed': 0,
                    'minutes_played': total_player_minutes.get(player_name, 0),
                    'position': primary_positions_by_player.get(player_name, 'N/A'),
                    'primary_position_minutes': position_minutes_summary.get(player_name, {}).get('primary_minutes', 0.0),
                    'secondary_positions': position_minutes_summary.get(player_name, {}).get('secondary_positions', ''),
                    'secondary_positions_minutes': position_minutes_summary.get(player_name, {}).get('secondary_minutes', 0.0)
                }
            # Count counter pressures (any)
            player_stats[player_name]['counter_pressures'] += 1

        # Count successful counter pressures and pressures by labels
        for ev in all_successful_counter_pressures:
            pname = ev['player']
            if pname not in player_stats:
                player_stats[pname] = {
                    'team': ev['team'],
                    'xG': 0.0,
                    'xA': 0.0,
                    'PSxG': 0.0,
                    'shots': 0,
                    'pbd': 0.0,
                    'pbp': 0.0,
                    'takeons': 0,
                    'takeons_total': 0,
                    'passes_to_box': 0,
                    'keypasses': 0,
                    'counter_pressures': 0,
                    'successful_counter_pressures': 0,
                    'successful_pressures': 0,
                    'progressive_carries': 0,
                    'progressive_passes': 0,
                    'goals_prevented': 0.0,
                    'psxg_faced': 0.0,
                    'goals_allowed': 0,
                    'minutes_played': total_player_minutes.get(pname, 0),
                    'position': primary_positions_by_player.get(pname, 'N/A'),
                    'primary_position_minutes': position_minutes_summary.get(pname, {}).get('primary_minutes', 0.0),
                    'secondary_positions': position_minutes_summary.get(pname, {}).get('secondary_positions', ''),
                    'secondary_positions_minutes': position_minutes_summary.get(pname, {}).get('secondary_minutes', 0.0)
                }
            player_stats[pname]['successful_counter_pressures'] = player_stats[pname].get('successful_counter_pressures', 0) + 1

        for ev in all_successful_pressures:
            pname = ev['player']
            if pname not in player_stats:
                player_stats[pname] = {
                    'team': ev['team'],
                    'xG': 0.0,
                    'xA': 0.0,
                    'PSxG': 0.0,
                    'shots': 0,
                    'pbd': 0.0,
                    'pbp': 0.0,
                    'takeons': 0,
                    'takeons_total': 0,
                    'passes_to_box': 0,
                    'keypasses': 0,
                    'counter_pressures': 0,
                    'successful_counter_pressures': 0,
                    'successful_pressures': 0,
                    'progressive_carries': 0,
                    'progressive_passes': 0,
                    'goals_prevented': 0.0,
                    'psxg_faced': 0.0,
                    'goals_allowed': 0,
                    'minutes_played': total_player_minutes.get(pname, 0),
                    'position': primary_positions_by_player.get(pname, 'N/A'),
                    'primary_position_minutes': position_minutes_summary.get(pname, {}).get('primary_minutes', 0.0),
                    'secondary_positions': position_minutes_summary.get(pname, {}).get('secondary_positions', ''),
                    'secondary_positions_minutes': position_minutes_summary.get(pname, {}).get('secondary_minutes', 0.0)
                }
            player_stats[pname]['successful_pressures'] = player_stats[pname].get('successful_pressures', 0) + 1
        
        # Process goalkeeper events for GK performance calculation
        for gk_event in all_gk_events:
            gk_name = gk_event['goalkeeper']
            if gk_name not in player_stats:
                player_stats[gk_name] = {
                    'team': gk_event['team'],
                    'xG': 0.0,
                    'xA': 0.0,
                    'PSxG': 0.0,
                    'shots': 0,
                    'pbd': 0.0,
                    'pbp': 0.0,
                    'takeons': 0,
                    'takeons_total': 0,
                    'passes_to_box': 0,
                    'keypasses': 0,
                    'counter_pressures': 0,
                    'progressive_carries': 0,
                    'progressive_passes': 0,
                    'goals_prevented': 0.0,
                    'psxg_faced': 0.0,
                    'goals_allowed': 0,
                    'minutes_played': total_player_minutes.get(gk_name, 0),
                    'position': primary_positions_by_player.get(gk_name, 'N/A'),
                    'primary_position_minutes': position_minutes_summary.get(gk_name, {}).get('primary_minutes', 0.0),
                    'secondary_positions': position_minutes_summary.get(gk_name, {}).get('secondary_positions', ''),
                    'secondary_positions_minutes': position_minutes_summary.get(gk_name, {}).get('secondary_minutes', 0.0)
                }
            
            # Add PSxG faced for all save attempts (both successful and unsuccessful)
            # PSxG faced = 1 - xS for each save attempt
            player_stats[gk_name]['psxg_faced'] += (1.0 - gk_event['xs'])

        # Process progressive carries
        for pc in all_progressive_carries:
            player_name = pc['player']
            if player_name not in player_stats:
                player_stats[player_name] = {
                    'team': pc['team'],
                    'xG': 0.0,
                    'xA': 0.0,
                    'PSxG': 0.0,
                    'shots': 0,
                    'pbd': 0.0,
                    'pbp': 0.0,
                    'takeons': 0,
                    'takeons_total': 0,
                    'passes_to_box': 0,
                    'keypasses': 0,
                    'counter_pressures': 0,
                    'progressive_carries': 0,
                    'progressive_passes': 0,
                    'goals_prevented': 0.0,
                    'psxg_faced': 0.0,
                    'goals_allowed': 0,
                    'minutes_played': total_player_minutes.get(player_name, 0),
                    'position': primary_positions_by_player.get(player_name, 'N/A'),
                    'primary_position_minutes': position_minutes_summary.get(player_name, {}).get('primary_minutes', 0.0),
                    'secondary_positions': position_minutes_summary.get(player_name, {}).get('secondary_positions', ''),
                    'secondary_positions_minutes': position_minutes_summary.get(player_name, {}).get('secondary_minutes', 0.0)
                }
            player_stats[player_name]['progressive_carries'] += 1

        # Process passes: progression by passes (sum of abs(negative goal progression)), progressive passes (gp < -10), xA, and key passes (label 82)
        for p in all_passes:
            player_name = p['player']
            if player_name not in player_stats:
                player_stats[player_name] = {
                    'team': p['team'],
                    'xG': 0.0,
                    'xA': 0.0,
                    'PSxG': 0.0,
                    'shots': 0,
                    'pbd': 0.0,
                    'pbp': 0.0,
                    'takeons': 0,
                    'takeons_total': 0,
                    'passes_to_box': 0,
                    'keypasses': 0,
                    'counter_pressures': 0,
                    'successful_crosses': 0,
                    'successful_counter_pressures': 0,
                    'successful_pressures': 0,
                    'progressive_carries': 0,
                    'progressive_passes': 0,
                    'goals_prevented': 0.0,
                    'psxg_faced': 0.0,
                    'goals_allowed': 0,
                    'minutes_played': total_player_minutes.get(player_name, 0),
                    'position': primary_positions_by_player.get(player_name, 'N/A'),
                    'primary_position_minutes': position_minutes_summary.get(player_name, {}).get('primary_minutes', 0.0),
                    'secondary_positions': position_minutes_summary.get(player_name, {}).get('secondary_positions', ''),
                    'secondary_positions_minutes': position_minutes_summary.get(player_name, {}).get('secondary_minutes', 0.0)
                }
            gp = p.get('goal_progression')
            xa_val = p.get('xA', 0.0) or 0.0
            labels = p.get('labels', []) or []
            try:
                if gp is not None:
                    if gp < 0:
                        player_stats[player_name]['pbp'] += abs(gp)
                    if gp < -10:
                        player_stats[player_name]['progressive_passes'] += 1
                # Sum xA
                player_stats[player_name]['xA'] = player_stats[player_name].get('xA', 0.0) + float(xa_val)
                # Count key passes (label 82)
                if 82 in labels:
                    player_stats[player_name]['keypasses'] = player_stats[player_name].get('keypasses', 0) + 1
                # Count successful crosses (label 101)
                if 101 in labels:
                    player_stats[player_name]['successful_crosses'] = player_stats[player_name].get('successful_crosses', 0) + 1
            except Exception:
                # Ignore malformed values
                pass

        # Process air duels, tackles, and interceptions
        for ev in all_air_duel_totals:
            pname = ev['player']
            if pname not in player_stats:
                player_stats[pname] = {
                    'team': ev['team'],
                    'xG': 0.0,
                    'xA': 0.0,
                    'PSxG': 0.0,
                    'shots': 0,
                    'pbd': 0.0,
                    'pbp': 0.0,
                    'takeons': 0,
                    'takeons_total': 0,
                    'passes_to_box': 0,
                    'keypasses': 0,
                    'successful_crosses': 0,
                    'successful_counter_pressures': 0,
                    'successful_pressures': 0,
                    'air_duels_won': 0,
                    'air_duels_total': 0,
                    'air_duels_win_pct': 0.0,
                    'successful_tackles': 0,
                    'successful_interceptions': 0,
                    'counter_pressures': 0,
                    'progressive_carries': 0,
                    'progressive_passes': 0,
                    'goals_prevented': 0.0,
                    'psxg_faced': 0.0,
                    'goals_allowed': 0,
                    'minutes_played': total_player_minutes.get(pname, 0),
                    'position': primary_positions_by_player.get(pname, 'N/A'),
                    'primary_position_minutes': position_minutes_summary.get(pname, {}).get('primary_minutes', 0.0),
                    'secondary_positions': position_minutes_summary.get(pname, {}).get('secondary_positions', ''),
                    'secondary_positions_minutes': position_minutes_summary.get(pname, {}).get('secondary_minutes', 0.0)
                }
            player_stats[pname]['air_duels_total'] = player_stats[pname].get('air_duels_total', 0) + 1

        for ev in all_air_duel_wins:
            pname = ev['player']
            if pname not in player_stats:
                player_stats[pname] = {
                    'team': ev['team'],
                    'xG': 0.0,
                    'xA': 0.0,
                    'PSxG': 0.0,
                    'shots': 0,
                    'pbd': 0.0,
                    'pbp': 0.0,
                    'takeons': 0,
                    'takeons_total': 0,
                    'passes_to_box': 0,
                    'keypasses': 0,
                    'successful_crosses': 0,
                    'successful_counter_pressures': 0,
                    'successful_pressures': 0,
                    'air_duels_won': 0,
                    'air_duels_total': 0,
                    'air_duels_win_pct': 0.0,
                    'successful_tackles': 0,
                    'successful_interceptions': 0,
                    'counter_pressures': 0,
                    'progressive_carries': 0,
                    'progressive_passes': 0,
                    'goals_prevented': 0.0,
                    'psxg_faced': 0.0,
                    'goals_allowed': 0,
                    'minutes_played': total_player_minutes.get(pname, 0),
                    'position': primary_positions_by_player.get(pname, 'N/A'),
                    'primary_position_minutes': position_minutes_summary.get(pname, {}).get('primary_minutes', 0.0),
                    'secondary_positions': position_minutes_summary.get(pname, {}).get('secondary_positions', ''),
                    'secondary_positions_minutes': position_minutes_summary.get(pname, {}).get('secondary_minutes', 0.0)
                }
            player_stats[pname]['air_duels_won'] = player_stats[pname].get('air_duels_won', 0) + 1

        for ev in all_successful_tackles:
            pname = ev['player']
            if pname not in player_stats:
                player_stats[pname] = {
                    'team': ev['team'],
                    'xG': 0.0,
                    'xA': 0.0,
                    'PSxG': 0.0,
                    'shots': 0,
                    'pbd': 0.0,
                    'pbp': 0.0,
                    'takeons': 0,
                    'takeons_total': 0,
                    'passes_to_box': 0,
                    'keypasses': 0,
                    'successful_crosses': 0,
                    'successful_counter_pressures': 0,
                    'successful_pressures': 0,
                    'air_duels_won': 0,
                    'air_duels_total': 0,
                    'air_duels_win_pct': 0.0,
                    'successful_tackles': 0,
                    'successful_interceptions': 0,
                    'counter_pressures': 0,
                    'progressive_carries': 0,
                    'progressive_passes': 0,
                    'goals_prevented': 0.0,
                    'psxg_faced': 0.0,
                    'goals_allowed': 0,
                    'minutes_played': total_player_minutes.get(pname, 0),
                    'position': primary_positions_by_player.get(pname, 'N/A'),
                    'primary_position_minutes': position_minutes_summary.get(pname, {}).get('primary_minutes', 0.0),
                    'secondary_positions': position_minutes_summary.get(pname, {}).get('secondary_positions', ''),
                    'secondary_positions_minutes': position_minutes_summary.get(pname, {}).get('secondary_minutes', 0.0)
                }
            player_stats[pname]['successful_tackles'] = player_stats[pname].get('successful_tackles', 0) + 1

        for ev in all_successful_interceptions:
            pname = ev['player']
            if pname not in player_stats:
                player_stats[pname] = {
                    'team': ev['team'],
                    'xG': 0.0,
                    'xA': 0.0,
                    'PSxG': 0.0,
                    'shots': 0,
                    'pbd': 0.0,
                    'pbp': 0.0,
                    'takeons': 0,
                    'takeons_total': 0,
                    'passes_to_box': 0,
                    'keypasses': 0,
                    'successful_crosses': 0,
                    'successful_counter_pressures': 0,
                    'successful_pressures': 0,
                    'air_duels_won': 0,
                    'air_duels_total': 0,
                    'air_duels_win_pct': 0.0,
                    'successful_tackles': 0,
                    'successful_interceptions': 0,
                    'counter_pressures': 0,
                    'progressive_carries': 0,
                    'progressive_passes': 0,
                    'goals_prevented': 0.0,
                    'psxg_faced': 0.0,
                    'goals_allowed': 0,
                    'minutes_played': total_player_minutes.get(pname, 0),
                    'position': primary_positions_by_player.get(pname, 'N/A'),
                    'primary_position_minutes': position_minutes_summary.get(pname, {}).get('primary_minutes', 0.0),
                    'secondary_positions': position_minutes_summary.get(pname, {}).get('secondary_positions', ''),
                    'secondary_positions_minutes': position_minutes_summary.get(pname, {}).get('secondary_minutes', 0.0)
                }
            player_stats[pname]['successful_interceptions'] = player_stats[pname].get('successful_interceptions', 0) + 1

        # Compute air duel win percentage
        for pname, stats in player_stats.items():
            total_duels = stats.get('air_duels_total', 0)
            wins = stats.get('air_duels_won', 0)
            stats['air_duels_win_pct'] = (100.0 * wins / total_duels) if total_duels > 0 else 0.0

        # Ensure all players present in stats have position-minute summaries (in case created before summaries)
        for pname, stats in player_stats.items():
            if 'primary_position_minutes' not in stats:
                stats['primary_position_minutes'] = position_minutes_summary.get(pname, {}).get('primary_minutes', 0.0)
            if 'secondary_positions' not in stats:
                stats['secondary_positions'] = position_minutes_summary.get(pname, {}).get('secondary_positions', '')
            if 'secondary_positions_minutes' not in stats:
                stats['secondary_positions_minutes'] = position_minutes_summary.get(pname, {}).get('secondary_minutes', 0.0)
        
        # Count goals allowed by grouping unsuccessful saves per goalkeeper
        unsuccessful_saves_by_gk = {}
        for gk_event in all_gk_events:
            if gk_event.get('is_unsuccessful_save', False):
                gk_name = gk_event['goalkeeper']
                if gk_name not in unsuccessful_saves_by_gk:
                    unsuccessful_saves_by_gk[gk_name] = []
                unsuccessful_saves_by_gk[gk_name].append(gk_event)
        
        # Set goals allowed to the length of unsuccessful saves list for each goalkeeper
        for gk_name, unsuccessful_saves in unsuccessful_saves_by_gk.items():
            if gk_name in player_stats:
                player_stats[gk_name]['goals_allowed'] = len(unsuccessful_saves)
        
        # Calculate PSxG - xG for each player
        for player in player_stats:
            player_stats[player]['PSxG_minus_xG'] = player_stats[player]['PSxG'] - player_stats[player]['xG']
        
        # Calculate Goals Prevented for goalkeepers (PSxG Faced - Goals Allowed)
        for player in player_stats:
            player_stats[player]['goals_prevented'] = player_stats[player]['psxg_faced'] - player_stats[player]['goals_allowed']
        
        # Calculate take-on success percentage
        for player in player_stats:
            if player_stats[player]['takeons_total'] > 0:
                player_stats[player]['takeon_success_pct'] = (player_stats[player]['takeons'] / player_stats[player]['takeons_total']) * 100
            else:
                player_stats[player]['takeon_success_pct'] = 0.0
        
        # Filter out invalid player names and sort by xG (descending)
        valid_players = {name: stats for name, stats in player_stats.items() 
                        if name and name != 'NOT_APPLICABLE' and name != 'Unknown' and name.strip()}
        sorted_players = sorted(valid_players.items(), key=lambda x: x[1]['xG'], reverse=True)
        
        # Global player selector (applies to Dashboard and Percentiles)
        st.markdown("**Player selection**")
        global_player_options = sorted(list({name for name in valid_players.keys()}))
        selected_player_global = st.selectbox("Select player", options=global_player_options)

        # Rating color function
        def _rating_color(rating_0_100: float) -> str:
            # 10-step bins, 0-10 dark red to 90-100 dark green
            palette = [
                "#8b0000", "#b22222", "#dc143c", "#ff4500", "#ff8c00",
                "#ffd700", "#9acd32", "#32cd32", "#228b22", "#006400"
            ]
            idx = int(min(9, max(0, rating_0_100 // 10)))
            return palette[int(idx)]

        analysis_tab, percentiles_tab, dashboard_tab = st.tabs(["Analysis", "Percentiles", "Dashboard"])

        with analysis_tab:
            st.subheader("Player Performance Analysis")
            
            # Filters
            col1, col2, col3 = st.columns([1, 1, 2])
            
            with col1:
                num_players = st.selectbox(
                    "Number of players to show:",
                    options=[10, 20, 50, 100, len(sorted_players)],
                    index=0
                )
            
            with col2:
                min_minutes = st.slider(
                    "Minimum minutes played:",
                    min_value=0,
                    max_value=500,
                    value=0,
                    step=5
                )
            
            with col3:
                per_96_minutes = st.checkbox("Show stats per 96 minutes", value=False)
                if per_96_minutes:
                    st.caption("Stats will be normalized to 96 minutes (full match equivalent)")
            
            # Filter players by minimum minutes
            filtered_players = [(name, stats) for name, stats in sorted_players if stats['minutes_played'] >= min_minutes]
            
            # Display summary
            st.write(f"**Analysis Summary:**")
            st.write(f"• {len(all_events_data)} matches analyzed")
            st.write(f"• {len(total_player_minutes)} total players found")
            st.write(f"• {len(filtered_players)} players with ≥{min_minutes} minutes played")
            st.write(f"• Showing top {min(num_players, len(filtered_players))} players by xG")
            
            # Create player table
            if filtered_players:
                # Prepare data for the table
                table_data = []
                for i, (player_name, stats) in enumerate(filtered_players[:num_players]):
                    # Calculate per-96-minutes stats if requested
                    if per_96_minutes and stats['minutes_played'] > 0:
                        multiplier = 96 / stats['minutes_played']
                        xg_display = f"{stats['xG'] * multiplier:.3f}"
                        xa_display = f"{stats.get('xA', 0.0) * multiplier:.3f}"
                        psxg_display = f"{stats['PSxG'] * multiplier:.3f}"
                        psxg_minus_xg_display = f"{stats['PSxG_minus_xG'] * multiplier:.3f}"
                        shots_display = f"{stats['shots'] * multiplier:.1f}"
                        pbd_display = f"{stats['pbd'] * multiplier:.1f}"
                        pbp_display = f"{stats.get('pbp', 0.0) * multiplier:.1f}"
                        takeons_display = f"{stats['takeons'] * multiplier:.1f}"
                        takeon_success_pct_display = f"{stats['takeon_success_pct']:.1f}%"
                        passes_to_box_display = f"{stats['passes_to_box'] * multiplier:.1f}"
                        counter_pressures_display = f"{stats['counter_pressures'] * multiplier:.1f}"
                        progressive_passes_display = f"{stats.get('progressive_passes', 0) * multiplier:.1f}"
                        successful_crosses_display = f"{stats.get('successful_crosses', 0) * multiplier:.1f}"
                        successful_counter_pressures_display = f"{stats.get('successful_counter_pressures', 0) * multiplier:.1f}"
                        successful_pressures_display = f"{stats.get('successful_pressures', 0) * multiplier:.1f}"
                        goals_prevented_display = f"{stats['goals_prevented'] * multiplier:.2f}"
                        psxg_faced_display = f"{stats['psxg_faced'] * multiplier:.2f}"
                        goals_allowed_display = f"{stats['goals_allowed'] * multiplier:.1f}"
                        progressive_carries_display = f"{stats.get('progressive_carries', 0) * multiplier:.1f}"
                        air_duels_won_display = f"{stats.get('air_duels_won', 0) * multiplier:.1f}"
                        successful_tackles_display = f"{stats.get('successful_tackles', 0) * multiplier:.1f}"
                        successful_interceptions_display = f"{stats.get('successful_interceptions', 0) * multiplier:.1f}"
                    else:
                        xg_display = f"{stats['xG']:.3f}"
                        xa_display = f"{stats.get('xA', 0.0):.3f}"
                        psxg_display = f"{stats['PSxG']:.3f}"
                        psxg_minus_xg_display = f"{stats['PSxG_minus_xG']:.3f}"
                        shots_display = f"{stats['shots']:.0f}"
                        pbd_display = f"{stats['pbd']:.1f}"
                        pbp_display = f"{stats.get('pbp', 0.0):.1f}"
                        takeons_display = f"{stats['takeons']:.0f}"
                        takeon_success_pct_display = f"{stats['takeon_success_pct']:.1f}%"
                        passes_to_box_display = f"{stats['passes_to_box']:.0f}"
                        counter_pressures_display = f"{stats['counter_pressures']:.0f}"
                        progressive_passes_display = f"{stats.get('progressive_passes', 0):.0f}"
                        successful_crosses_display = f"{stats.get('successful_crosses', 0):.0f}"
                        successful_counter_pressures_display = f"{stats.get('successful_counter_pressures', 0):.0f}"
                        successful_pressures_display = f"{stats.get('successful_pressures', 0):.0f}"
                        goals_prevented_display = f"{stats['goals_prevented']:.2f}"
                        psxg_faced_display = f"{stats['psxg_faced']:.2f}"
                        goals_allowed_display = f"{stats['goals_allowed']:.0f}"
                        progressive_carries_display = f"{stats.get('progressive_carries', 0):.0f}"
                        air_duels_won_display = f"{stats.get('air_duels_won', 0):.0f}"
                        successful_tackles_display = f"{stats.get('successful_tackles', 0):.0f}"
                        successful_interceptions_display = f"{stats.get('successful_interceptions', 0):.0f}"
                    
                    table_data.append({
                        'Rank': i + 1,
                        'Player': player_name,
                        'Team': stats['team'],
                        'Position': stats.get('position', 'N/A'),
                        '2nd/3rd Positions': stats.get('secondary_positions', ''),
                        'Minutes': f"{stats['minutes_played']:.0f}",
                        'xG': xg_display,
                        'xA': xa_display,
                        'PSxG': psxg_display,
                        'PSxG - xG': psxg_minus_xg_display,
                        'PBD': pbd_display,
                        'PBP': pbp_display,
                        'Key passes': f"{stats.get('keypasses', 0):.0f}" if not per_96_minutes else f"{stats.get('keypasses', 0) * multiplier:.1f}",
                        'Progressive Passes': progressive_passes_display,
                        'Successful Crosses': successful_crosses_display,
                        'Successful Counter Pressures': successful_counter_pressures_display,
                        'Successful Pressures': successful_pressures_display,
                        'Take-ons': takeons_display,
                        'Take-on %': takeon_success_pct_display,
                        'Progressive Carries': progressive_carries_display,
                        'Passes to Box': passes_to_box_display,
                        'Air Duels Won': air_duels_won_display,
                        'Air Duels Win %': f"{stats.get('air_duels_win_pct', 0.0):.1f}%",
                        'Successful Tackles': successful_tackles_display,
                        'Successful Interceptions': successful_interceptions_display,
                        'Goals Prevented': goals_prevented_display,
                        'PSxG Faced': psxg_faced_display,
                        'Goals Allowed': goals_allowed_display,
                        'Shots': shots_display
                    })
                
                # Display the table
                st.dataframe(
                    table_data,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Rank": st.column_config.NumberColumn("Rank", width="small"),
                        "Player": st.column_config.TextColumn("Player", width="medium"),
                        "Team": st.column_config.TextColumn("Team", width="small"),
                        "Position": st.column_config.TextColumn("Position", width="small"),
                        "2nd/3rd Positions": st.column_config.TextColumn("2nd/3rd Positions", width="small"),
                        "Minutes": st.column_config.NumberColumn("Minutes", width="small"),
                        "xG": st.column_config.NumberColumn("xG", width="small", format="%.3f"),
                            "xA": st.column_config.NumberColumn("xA", width="small", format="%.3f"),
                        "PSxG": st.column_config.NumberColumn("PSxG", width="small", format="%.3f"),
                        "PSxG - xG": st.column_config.NumberColumn("PSxG - xG", width="small", format="%.3f"),
                        "PBD": st.column_config.NumberColumn("PBD", width="small", format="%.1f", help="Progression By Dribble (meters)"),
                        "PBP": st.column_config.NumberColumn("PBP", width="small", format="%.1f", help="Progression By Passes (meters)"),
                            "Key passes": st.column_config.NumberColumn("Key passes", width="small"),
                        "Progressive Passes": st.column_config.NumberColumn("Progressive Passes", width="small"),
                            "Successful Crosses": st.column_config.NumberColumn("Successful Crosses", width="small"),
                            "Successful Counter Pressures": st.column_config.NumberColumn("Successful Counter Pressures", width="small"),
                            "Successful Pressures": st.column_config.NumberColumn("Successful Pressures", width="small"),
                        "Take-ons": st.column_config.NumberColumn("Take-ons", width="small", format="%.0f", help="Successful take-ons (label 121)"),
                        "Take-on %": st.column_config.TextColumn("Take-on %", width="small", help="Take-on success percentage"),
                        "Progressive Carries": st.column_config.NumberColumn("Progressive Carries", width="small"),
                        "Air Duels Won": st.column_config.NumberColumn("Air Duels Won", width="small"),
                        "Air Duels Win %": st.column_config.TextColumn("Air Duels Win %", width="small"),
                        "Successful Tackles": st.column_config.NumberColumn("Successful Tackles", width="small"),
                        "Successful Interceptions": st.column_config.NumberColumn("Successful Interceptions", width="small"),
                        "Passes to Box": st.column_config.NumberColumn("Passes to Box", width="small", format="%.0f", help="Successful passes to box (label 72)"),
                        "Goals Prevented": st.column_config.NumberColumn("Goals Prevented", width="small", format="%.2f", help="PSxG Faced - Goals Allowed"),
                        "PSxG Faced": st.column_config.NumberColumn("PSxG Faced", width="small", format="%.2f", help="Total PSxG faced by goalkeeper"),
                        "Goals Allowed": st.column_config.NumberColumn("Goals Allowed", width="small", format="%.0f", help="Total goals allowed (unsuccessful saves)"),
                        "Shots": st.column_config.NumberColumn("Shots", width="small")
                    }
                )
            else:
                if min_minutes > 0:
                    st.info(f"No players found with at least {min_minutes} minutes played.")
                else:
                    st.info("No shot data found for player analysis.")

        with dashboard_tab:
            st.subheader("Dashboard")
            
            if selected_player_global:
                stats = valid_players[selected_player_global]
                
                # Left side: General statistics
                left_col, right_col = st.columns([1, 2])
                
                with left_col:
                    st.markdown("**General Statistics**")
                    st.metric("Team", stats['team'])
                    st.metric("Minutes Played", f"{stats['minutes_played']:.0f}")
                    st.metric("Primary Position", stats.get('position', 'N/A'))
                    st.metric("Position Group", stats.get('position_group', 'N/A'))
                    
                    # Key metrics
                    st.markdown("**Key Metrics**")
                    st.metric("Goals", f"{stats.get('goals', 0):.0f}")
                    st.metric("Assists", f"{stats.get('assists', 0):.0f}")
                    st.metric("xG", f"{stats.get('xG', 0):.2f}")
                    st.metric("xA", f"{stats.get('xA', 0):.2f}")
                    st.metric("Shots", f"{stats.get('shots', 0):.0f}")
                    st.metric("PBD (m)", f"{stats.get('pbd', 0):.0f}")
                    st.metric("Take-ons", f"{stats.get('takeons', 0):.0f}")
                    st.metric("Take-on %", f"{stats.get('takeon_success_pct', 0):.1f}%")
                
                with right_col:
                    # Pizza chart for key metrics
                    st.markdown("**Performance Overview**")
                    
                    # Prepare data for pizza chart
                    pizza_metrics = {
                        'Goals': stats.get('goals', 0),
                        'Assists': stats.get('assists', 0),
                        'xG': stats.get('xG', 0),
                        'xA': stats.get('xA', 0),
                        'Shots': stats.get('shots', 0),
                        'PBD (m)': stats.get('pbd', 0),
                        'Take-ons': stats.get('takeons', 0),
                        'Passes to Box': stats.get('passes_to_box', 0)
                    }
                    
                    # Filter out zero values and create pizza chart
                    non_zero_metrics = {k: v for k, v in pizza_metrics.items() if v > 0}
                    
                    if non_zero_metrics:
                        fig_pizza, ax_pizza = plt.subplots(figsize=(8, 6))
                        labels = list(non_zero_metrics.keys())
                        values = list(non_zero_metrics.values())
                        colors = plt.cm.Set3(np.linspace(0, 1, len(labels)))
                        
                        wedges, texts, autotexts = ax_pizza.pie(values, labels=labels, autopct='%1.1f%%', 
                                                               colors=colors, startangle=90)
                        
                        # Improve text appearance
                        for autotext in autotexts:
                            autotext.set_color('white')
                            autotext.set_fontweight('bold')
                        
                        ax_pizza.set_title(f"{selected_player_global} - Key Metrics Distribution")
                        st.pyplot(fig_pizza, use_container_width=True)
                    else:
                        st.info("No data available for pizza chart")
                
                # Metric group ratings below
                st.markdown("---")
                st.markdown("**Metric Group Ratings**")
                
                # Calculate overall rating first
                def calculate_overall_rating(player_stats, position_group):
                    """Calculate overall rating based on all available metrics"""
                    if position_group not in backs_groups:
                        return 50.0  # Default for non-backs
                    
                    group_metrics = backs_groups[position_group]
                    total_weight = 0
                    weighted_sum = 0
                    
                    for group_name, items in group_metrics.items():
                        for _, key in items:
                            val = player_stats.get(key, 0.0)
                            # Simple weight based on metric importance
                            weight = 1.0
                            total_weight += weight
                            weighted_sum += val * weight
                    
                    if total_weight == 0:
                        return 50.0
                    
                    # Normalize to 0-100 scale
                    avg_value = weighted_sum / total_weight
                    return max(0.0, min(100.0, avg_value * 10))  # Scale factor for visibility
                
                # Show overall rating
                overall_rating = calculate_overall_rating(stats, stats.get('position_group', ''))
                color = _rating_color(overall_rating)
                st.markdown(f"""
                <div style="background: {color}; 
                            color: white; padding: 15px 25px; border-radius: 10px; text-align: center; 
                            font-size: 24px; font-weight: bold; margin: 15px 0;">
                    Overall Rating: {overall_rating:.1f}
                </div>
                """, unsafe_allow_html=True)
                
                # Show metric group ratings
                position_group = stats.get('position_group', '')
                if position_group in backs_groups:
                    group_metrics = backs_groups[position_group]
                    
                    for group_name, items in group_metrics.items():
                        st.markdown(f"**{group_name}**")
                        
                        # Calculate group rating
                        group_total = 0
                        group_count = 0
                        for _, key in items:
                            val = stats.get(key, 0.0)
                            group_total += val
                            group_count += 1
                        
                        group_rating = (group_total / group_count * 10) if group_count > 0 else 0
                        group_rating = max(0.0, min(100.0, group_rating))
                        
                        # Display group rating
                        group_color = _rating_color(group_rating)
                        st.markdown(f"""
                        <div style="background: {group_color}; 
                                    color: white; padding: 8px 15px; border-radius: 6px; text-align: center; 
                                    font-size: 16px; font-weight: bold; margin: 5px 0; display: inline-block;">
                            {group_rating:.1f}
                        </div>
                        """, unsafe_allow_html=True)
                        
                        # Show individual metrics in this group
                        metric_cols = st.columns(len(items))
                        for (label, key), col in zip(items, metric_cols):
                            with col:
                                value = stats.get(key, 0.0)
                                st.metric(label, f"{value:.2f}")
                        
                        st.markdown("---")
                else:
                    st.info(f"Metric group ratings not available for position group: {position_group}")
            else:
                st.info("Please select a player to view dashboard")

        # Position groups mapping
        POSITION_GROUPS = {
            'Keepers': {'DM'},
            'Centrale verdedigers': {'CV'},
            'Backs': {'LV', 'RV', 'LVV', 'RVV'},
            'Middenvelders': {'VM', 'CM', 'AM'},
            'Vleugelspelers': {'LM', 'RM', 'LB', 'RB'},
            'Spitsen': {'SP'}
        }

        def get_position_group(mapped_position: str):
            if not mapped_position:
                return 'Onbekend'
            for group_name, positions in POSITION_GROUPS.items():
                if mapped_position in positions:
                    return group_name
            return 'Onbekend'

        # Attach position group to each valid player
        for pname, pstats in valid_players.items():
            mapped_pos = pstats.get('position', '')
            pstats['position_group'] = get_position_group(mapped_pos)

        with percentiles_tab:
            st.subheader("Percentiles per 96 by Position Group")

            # Metric selection for percentile computation
            metrics_catalog = {
                'xG': 'xG',
                'xA': 'xA',
                'Shots': 'shots',
                'PBD (m)': 'pbd',
                'PBP (m)': 'pbp',
                'Progressive Passes': 'progressive_passes',
                'Progressive Carries': 'progressive_carries',
                'Take-ons': 'takeons',
                'Take-on %': 'takeon_success_pct',
                'Passes to Box': 'passes_to_box',
                'Successful Crosses': 'successful_crosses',
                'Key passes': 'keypasses',
                'Air Duels Won': 'air_duels_won',
                'Air Duels Win %': 'air_duels_win_pct',
                'Successful Tackles': 'successful_tackles',
                'Successful Interceptions': 'successful_interceptions',
                'PSxG Faced': 'psxg_faced',
                'Goals Allowed': 'goals_allowed',
                'Goals Prevented': 'goals_prevented'
            }

            left, right = st.columns([2, 3])
            with left:
                # Auto-position group detection from global selection
                pos_groups = list(POSITION_GROUPS.keys())
                player_group_auto = valid_players.get(selected_player_global, {}).get('position_group', 'Onbekend')
                selected_group = st.selectbox("Position group", options=pos_groups, index=max(0, pos_groups.index(player_group_auto) if player_group_auto in pos_groups else 0))
                st.caption(f"Using group '{selected_group}' based on {selected_player_global}'s primary position" if player_group_auto in pos_groups else "Select a position group")
                per96 = st.checkbox("Per 96 minutes", value=True)
                show_percentile = st.checkbox("Show percentiles (0-100)", value=True)

            # Build dataset for the selected group (override to player's group if selected)
            effective_group = selected_group
            group_players = [(name, p) for name, p in valid_players.items() if p.get('position_group') == effective_group]
            # Compute per-96 values where applicable
            def value_per96(pstats, key):
                v = pstats.get(key, 0.0)
                if key.endswith('_pct') or key == 'air_duels_win_pct':
                    return float(v)
                if per96:
                    minutes = max(pstats.get('minutes_played', 0), 1e-9)
                    return float(v) * (96.0 / minutes) if minutes > 0 else 0.0
                return float(v)

            # Percentile helper (min-max within a given (vmin, vmax))
            def percentile_minmax(values_minmax, target_value):
                vmin, vmax = values_minmax
                # Guard against invalid ranges and clamp
                if vmax > vmin:
                    tv = float(target_value)
                    if tv < vmin:
                        tv = vmin
                    elif tv > vmax:
                        tv = vmax
                    return 100.0 * (tv - vmin) / (vmax - vmin)
                # All equal; return 50 to avoid NaN and indicate mid
                return 50.0

            def calculate_percentile_rank(values, target_value):
                """Calculate true percentile rank (better than X% of the group)."""
                if not values:
                    return 50.0
                sorted_values = sorted(values)
                count_below = sum(1 for v in sorted_values if v < target_value)
                count_equal = sum(1 for v in sorted_values if v == target_value)
                total_count = len(sorted_values)
                
                if total_count == 0:
                    return 50.0
                
                # Percentile rank = (count_below + 0.5 * count_equal) / total_count * 100
                percentile = (count_below + 0.5 * count_equal) / total_count * 100
                return max(0.0, min(100.0, percentile))

            with right:
                # Reserved for future summary; group sections below handle visuals and ratings
                st.empty()

            # Removed overall distribution plot in favor of per-group charts below

            # Metric groups for Backs only (for now)
            if effective_group == 'Backs':
                st.markdown("**Metric Groups (Backs)**")

                backs_groups = {
                    'Dribbelen': [
                        ('PBD (m)', 'pbd'),
                        ('Progressive Carries', 'progressive_carries'),
                        ('Take-ons', 'takeons'),
                        ('Take-on %', 'takeon_success_pct')
                    ],
                    'Opbouwen': [
                        ('PBP (m)', 'pbp'),
                        ('Progressive Passes', 'progressive_passes')
                    ],
                    'Eindfase': [
                        ('xA', 'xA'),
                        ('Crosses', 'successful_crosses'),
                        ('Key passes', 'keypasses'),
                        ('xG', 'xG'),
                        ('Passes to Box', 'passes_to_box')
                    ],
                    'Verdedigen': [
                        ('Air Duels Won', 'air_duels_won'),
                        ('Air Duels Win %', 'air_duels_win_pct'),
                        ('Successful Tackles', 'successful_tackles'),
                        ('Successful Interceptions', 'successful_interceptions')
                    ]
                }


                def badge(text: str, value: float, is_pct: bool) -> str:
                    val_display = f"{value:.1f}%" if is_pct else f"{value:.1f}"
                    color = _rating_color(value if is_pct else value)
                    return f"<span style='background:{color};color:white;padding:6px 10px;border-radius:6px;font-weight:600;'>{text}: {val_display}</span>"

                def render_group_section(group_name, items):
                    st.markdown(f"### {group_name}")
                    # Prepare distributions and weights
                    metrics_keys_local = [key for _, key in items]
                    distributions_local = {k: [value_per96(p, k) for _, p in group_players] for k in metrics_keys_local}
                    minmax_local = {}
                    for k, vals in distributions_local.items():
                        if vals:
                            vmin = float(min(vals)); vmax = float(max(vals))
                        else:
                            vmin = 0.0; vmax = 0.0
                        minmax_local[k] = (vmin, vmax)

                    # Weights (compute first, display later)
                    cols = st.columns(len(items))
                    weights = {key: 1.0 for _, key in items}
                    total_w = sum(weights.values())
                    norm_weights = {k: (w / total_w if total_w > 0 else 0.0) for k, w in weights.items()}

                    # Overall rating badge (using current weights)
                    rating_value = None
                    sel_stats = valid_players.get(selected_player_global)
                    if sel_stats and sel_stats.get('position_group') == effective_group:
                        parts = []
                        for _, key in items:
                            val = value_per96(sel_stats, key)
                            pct = calculate_percentile_rank(distributions_local[key], val)
                            parts.append(pct * norm_weights[key])
                        rating_value = max(0.0, min(100.0, sum(parts)))
                    if rating_value is not None:
                        # Larger overall rating without percentage sign
                        color = _rating_color(rating_value)
                        st.markdown(f"""
                        <div style="background: {color}; 
                                    color: white; padding: 12px 20px; border-radius: 8px; text-align: center; 
                                    font-size: 18px; font-weight: bold; margin: 10px 0;">
                            {group_name}: {rating_value:.1f}
                        </div>
                        """, unsafe_allow_html=True)

                    # Per-metric percentile badges for selected player
                    sel_stats = valid_players.get(selected_player_global)
                    if sel_stats and sel_stats.get('position_group') == effective_group:
                        cols_pct = st.columns(len(items))
                        for (label, key), c in zip(items, cols_pct):
                            with c:
                                val = value_per96(sel_stats, key)
                                pct = calculate_percentile_rank(distributions_local[key], val)
                                st.markdown(badge(label, pct, is_pct=True), unsafe_allow_html=True)

                    # Weights UI (display now, allow user to adjust)
                    cols_w = st.columns(len(items))
                    for (label, key), c in zip(items, cols_w):
                        with c:
                            weights[key] = st.slider(f"{label} weight", 0.0, 2.0, 1.0, 0.1)
                    total_w = sum(weights.values())
                    norm_weights = {k: (w / total_w if total_w > 0 else 0.0) for k, w in weights.items()}

                    # Individual distribution plots per metric (true-value axes)
                    big3_teams = {"PSV", "Ajax", "Feyenoord"}
                    for (label, key) in items:
                        vals = distributions_local[key]
                        vmin = float(min(vals)) if vals else 0.0
                        vmax = float(max(vals)) if vals else 1.0
                        if vmax <= vmin:
                            vmax = vmin + 1.0
                        fig_m, ax_m = plt.subplots(figsize=(8, 2.8))
                        # Background bar spanning metric range
                        ax_m.barh([0], [vmax - vmin], left=vmin, color="#f7f7fb", edgecolor="none", height=0.6, zorder=1)
                        # All dots for players in group
                        x_vals = [float(v) for v in vals]
                        ax_m.scatter(x_vals, [0] * len(x_vals), s=14, color="#8a8a8a", alpha=0.65, zorder=2)
                        # Competition average
                        if vals:
                            comp_avg = float(np.mean(x_vals))
                            ax_m.vlines(comp_avg, -0.28, 0.28, linestyle=(0, (4, 4)), color="#4d4d4d", linewidth=1.4, zorder=1)
                        # Top 3 average
                        big3_vals = []
                        for nm, p in group_players:
                            team_name = str(p.get('team', '') or '')
                            if any(t.lower() in team_name.lower() for t in big3_teams):
                                big3_vals.append(value_per96(p, key))
                        if big3_vals:
                            big3_avg = float(np.mean(big3_vals))
                            ax_m.vlines(big3_avg, -0.28, 0.28, linestyle=(0, (2, 3)), color="#d62728", linewidth=1.4, zorder=1)
                        # Selected player point
                        if sel_stats and sel_stats.get('position_group') == effective_group:
                            sel_val = value_per96(sel_stats, key)
                            ax_m.scatter([sel_val], [0], s=90, color="#1f77b4", edgecolor="white", linewidth=0.8, zorder=3)
                        # Axes styling per metric
                        ax_m.set_title(label)
                        ax_m.set_yticks([])
                        # Choose ticks based on value range - more logical and more ticks
                        rng = vmax - vmin
                        if rng <= 1:
                            step = 0.1
                        elif rng <= 5:
                            step = 0.5
                        elif rng <= 10:
                            step = 1.0
                        elif rng <= 25:
                            step = 2.5
                        elif rng <= 50:
                            step = 5.0
                        elif rng <= 100:
                            step = 10.0
                        else:
                            step = 20.0
                        
                        # Generate ticks that include min and max
                        ticks = []
                        current = vmin
                        while current <= vmax + 1e-9:
                            ticks.append(current)
                            current += step
                        # Ensure max is included
                        if ticks[-1] < vmax:
                            ticks.append(vmax)
                        
                        ax_m.set_xlim(left=vmin, right=vmax)
                        ax_m.set_xticks(ticks)
                        ax_m.grid(axis='x', alpha=0.15)
                        for spine in ["top", "right", "left", "bottom"]:
                            ax_m.spines[spine].set_visible(False)
                        st.pyplot(fig_m, use_container_width=True)

                # Render all backs groups
                for gname, items in backs_groups.items():
                    render_group_section(gname, items)
            else:
                st.info("Metric groups are currently only available for Backs. Select a back or the Backs group.")