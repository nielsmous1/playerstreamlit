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

        # Metric groups for Backs (shared across tabs)
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
                ('Successful Interceptions', 'successful_interceptions'),
                ('Successful Pressures', 'successful_pressures')
            ]
        }

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

        # Helper function for per-96 minute calculations
        def get_value_per96(pstats, key):
            value = pstats.get(key, 0.0)
            minutes = max(pstats.get('minutes_played', 0), 1e-9)
            return float(value) * (96.0 / minutes) if minutes > 0 else 0.0

        # Function to calculate match-specific stats
        def calculate_match_stats(events, player_name):
            """Calculate per-96 minute stats for a specific match"""
            # Ensure events is a list
            if isinstance(events, dict):
                events = events.get('data', [])
            
            player_minutes = calculate_player_minutes(events)
            if player_name not in player_minutes or player_minutes[player_name] <= 0:
                return None
            
            minutes = player_minutes[player_name]
            
            # Initialize match stats
            match_stats = {
                'minutes_played': minutes,
                'pbd': 0.0,
                'progressive_carries': 0.0,
                'takeons': 0.0,
                'takeon_success_pct': 0.0,
                'pbp': 0.0,
                'progressive_passes': 0.0,
                'xA': 0.0,
                'successful_crosses': 0.0,
                'keypasses': 0.0,
                'xG': 0.0,
                'passes_to_box': 0.0,
                'air_duels_won': 0.0,
                'air_duels_win_pct': 0.0,
                'successful_tackles': 0.0,
                'successful_interceptions': 0.0,
                'successful_pressures': 0.0
            }
            
            # Calculate actual stats for this match
            # Find events for this specific player
            player_events = [e for e in events if e.get('playerName') == player_name]
            
            # Calculate PBD (Progressive Ball Distance)
            dribble_events = [e for e in player_events if e.get('baseTypeId') == 1 and e.get('subTypeId') == 10 and e.get('resultId') == 1]
            match_stats['pbd'] = sum(e.get('metrics', {}).get('pbd', 0) for e in dribble_events)
            
            # Calculate Progressive Carries
            carry_events = [e for e in player_events if e.get('baseTypeId') == 1 and e.get('subTypeId') == 10 and e.get('resultId') == 1 and 119 in e.get('labels', [])]
            match_stats['progressive_carries'] = len(carry_events)
            
            # Calculate Take-ons
            takeon_events = [e for e in player_events if e.get('baseTypeId') == 1 and e.get('subTypeId') == 10 and e.get('resultId') == 1 and e.get('labels') and (120 in e.get('labels', []) or 121 in e.get('labels', []))]
            match_stats['takeons'] = len(takeon_events)
            
            # Calculate Take-on success percentage
            all_takeon_attempts = [e for e in player_events if e.get('baseTypeId') == 1 and e.get('subTypeId') == 10 and e.get('labels') and (120 in e.get('labels', []) or 121 in e.get('labels', []))]
            successful_takeons = [e for e in all_takeon_attempts if e.get('resultId') == 1]
            match_stats['takeon_success_pct'] = (len(successful_takeons) / len(all_takeon_attempts) * 100) if all_takeon_attempts else 0.0
            
            # Calculate PBP (Progressive Ball Progression by Passes)
            pass_events = [e for e in player_events if e.get('baseTypeId') == 1 and e.get('subTypeId') == 1 and e.get('resultId') == 1]
            match_stats['pbp'] = sum(e.get('metrics', {}).get('goalProgression', 0) for e in pass_events)
            
            # Calculate Progressive Passes
            progressive_pass_events = [e for e in pass_events if e.get('metrics', {}).get('goalProgression', 0) < -10]
            match_stats['progressive_passes'] = len(progressive_pass_events)
            
            # Calculate xA
            match_stats['xA'] = sum(e.get('metrics', {}).get('xA', 0) for e in pass_events)
            
            # Calculate Successful Crosses
            cross_events = [e for e in pass_events if 101 in e.get('labels', [])]
            match_stats['successful_crosses'] = len(cross_events)
            
            # Calculate Key Passes
            key_pass_events = [e for e in pass_events if 82 in e.get('labels', [])]
            match_stats['keypasses'] = len(key_pass_events)
            
            # Calculate xG
            shot_events = [e for e in player_events if e.get('baseTypeId') == 1 and e.get('subTypeId') == 10 and e.get('resultId') == 1 and e.get('labels') and 16 in e.get('labels', [])]
            match_stats['xG'] = sum(e.get('metrics', {}).get('xG', 0) for e in shot_events)
            
            # Calculate Passes to Box
            passes_to_box_events = [e for e in pass_events if 72 in e.get('labels', [])]
            match_stats['passes_to_box'] = len(passes_to_box_events)
            
            # Calculate Air Duels Won
            air_duel_events = [e for e in player_events if e.get('baseTypeId') == 4 and e.get('subTypeId') == 402 and e.get('resultId') == 1]
            match_stats['air_duels_won'] = len(air_duel_events)
            
            # Calculate Air Duels Win Percentage
            all_air_duel_events = [e for e in player_events if e.get('baseTypeId') == 4 and e.get('subTypeId') == 402]
            match_stats['air_duels_win_pct'] = (len(air_duel_events) / len(all_air_duel_events) * 100) if all_air_duel_events else 0.0
            
            # Calculate Successful Tackles
            tackle_events = [e for e in player_events if e.get('baseTypeId') == 4 and e.get('subTypeId') == 400 and e.get('resultId') == 1]
            match_stats['successful_tackles'] = len(tackle_events)
            
            # Calculate Successful Interceptions
            interception_events = [e for e in player_events if e.get('baseTypeId') == 5 and e.get('subTypeId') == 500]
            match_stats['successful_interceptions'] = len(interception_events)
            
            # Calculate Successful Pressures
            pressure_events = [e for e in player_events if e.get('resultId') == 1 and 213 in e.get('labels', [])]
            match_stats['successful_pressures'] = len(pressure_events)
            
            # Convert to per-96 minutes
            for key in match_stats:
                if key != 'minutes_played' and key != 'takeon_success_pct' and key != 'air_duels_win_pct':
                    match_stats[key] = match_stats[key] * (96.0 / minutes) if minutes > 0 else 0.0
            
            return match_stats

        analysis_tab, dashboard_tab, percentiles_tab, dashboard2_tab = st.tabs(["Analysis", "Dashboard", "Percentiles", "Dashboard2"])

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
            dashboard_cols = st.columns([2, 2, 3])

            # Player info (uses global selection)
            with dashboard_cols[0]:
                selected_player = selected_player_global

            # Show standard info
            if selected_player:
                stats = valid_players[selected_player]
                with dashboard_cols[1]:
                    st.metric("Team", stats['team'])
                    st.metric("Minutes Played", f"{stats['minutes_played']:.0f}")
                    st.metric("Primary Position", stats.get('position', 'N/A'))

            # Radar chart controls
            with dashboard_cols[2]:
                st.markdown("**Radar Chart Settings**")
                available_metrics = {
                    'xG': 'xG',
                    'PSxG': 'PSxG',
                    'PSxG - xG': 'PSxG_minus_xG',
                    'Shots': 'shots',
                    'PBD (m)': 'pbd',
                    'Take-ons': 'takeons',
                    'Take-on %': 'takeon_success_pct',
                    'Passes to Box': 'passes_to_box',
                    'Counter Pressures': 'counter_pressures',
                    'Goals Prevented': 'goals_prevented',
                    'PSxG Faced': 'psxg_faced',
                    'Goals Allowed': 'goals_allowed'
                }
                default_selection = ['xG', 'Shots', 'PBD (m)', 'Take-ons', 'Passes to Box']
                selected_labels = st.multiselect(
                    "Select statistics",
                    options=list(available_metrics.keys()),
                    default=[m for m in default_selection if m in available_metrics]
                )
                per96 = st.checkbox("Per 96 minutes", value=False, help="Normalize stats to 96 minutes")
                normalize_percentile = st.checkbox("Percentile (0–100)", value=True, help="Convert metrics to percentile ranks across all players")

            # Build and show charts
            if selected_player and selected_labels:
                chosen_keys = [available_metrics[label] for label in selected_labels]

                # Prepare vectors
                def get_value(pstats, key):
                    value = pstats.get(key, 0.0)
                    if per96:
                        minutes = max(pstats.get('minutes_played', 0), 1e-9)
                        value = value * (96.0 / minutes) if minutes > 0 else 0.0
                    return float(value)

                selected_stats = valid_players[selected_player]
                player_values_raw = [get_value(selected_stats, k) for k in chosen_keys]

                # Percentile normalization helper
                def percentile_rank(values_list, target_value):
                    if not values_list:
                        return 0.0
                    # Handle metrics that can be negative by using raw value
                    less_equal = sum(1 for v in values_list if v <= target_value)
                    return 100.0 * less_equal / len(values_list)

                # Precompute raw distributions per metric
                distributions = {}
                for key in chosen_keys:
                    vals = []
                    for _, p in valid_players.items():
                        vals.append(get_value(p, key))
                    distributions[key] = vals

                if normalize_percentile:
                    radar_values = [percentile_rank(distributions[k], v) for k, v in zip(chosen_keys, player_values_raw)]
                    radar_suffix = " (percentile)"
                else:
                    radar_values = player_values_raw
                    radar_suffix = ""

                plot_cols = st.columns([3, 4])

                # Left: horizontal bar with all players' dots per metric
                with plot_cols[0]:
                    fig_h, ax_h = plt.subplots(figsize=(8, 6 + max(0, len(chosen_keys) - 5) * 0.4))
                    metrics_display = list(reversed(selected_labels))
                    keys_display = list(reversed(chosen_keys))
                    y_positions = np.arange(len(keys_display))

                    # Precompute per-metric scales, averages, and values
                    big3_teams = {"PSV", "Ajax", "Feyenoord"}
                    for idx, (label, key) in enumerate(zip(metrics_display, keys_display)):
                        # All players' values for this metric
                        values_raw = distributions[key]
                        values_all = []
                        big3_values_raw = []
                        for name, p in valid_players.items():
                            v = get_value(p, key)
                            vv = percentile_rank(values_raw, v) if normalize_percentile else v
                            values_all.append(vv)
                            team_name = str(p.get('team', '') or '')
                            if any(t.lower() in team_name.lower() for t in big3_teams):
                                big3_values_raw.append(v)

                        # Scales
                        if normalize_percentile:
                            xmax = 100.0
                        else:
                            xmax = max(values_raw) if values_raw else 1.0
                            if xmax == 0:
                                xmax = 1.0

                        y = y_positions[idx]
                        # Background bar
                        ax_h.barh(y, xmax, color="#f7f7fb", edgecolor="none", height=0.6, zorder=1)

                        # All players small grey dots
                        jitter = (np.random.rand(len(values_all)) - 0.5) * 0.15
                        ax_h.scatter(values_all, y + jitter, s=14, color="#8a8a8a", alpha=0.65, zorder=2)

                        # Selected player value
                        sel_v_raw = get_value(selected_stats, key)
                        sel_v = percentile_rank(values_raw, sel_v_raw) if normalize_percentile else sel_v_raw
                        ax_h.scatter([sel_v], [y], s=70, color="#1f77b4", edgecolor="white", linewidth=0.8, zorder=3, label="Selected player" if idx == 0 else None)

                        # Averages
                        if values_raw:
                            avg_raw = float(np.mean(values_raw))
                            avg_pct = percentile_rank(values_raw, avg_raw) if normalize_percentile else avg_raw
                            ax_h.vlines(avg_pct, y - 0.28, y + 0.28, linestyle=(0, (4, 4)), color="#4d4d4d", linewidth=1.4, zorder=1, label="Average" if idx == 0 else None)
                        if big3_values_raw:
                            avg_big3_raw = float(np.mean(big3_values_raw))
                            avg_big3_pct = percentile_rank(values_raw, avg_big3_raw) if normalize_percentile else avg_big3_raw
                            ax_h.vlines(avg_big3_pct, y - 0.28, y + 0.28, linestyle=(0, (2, 3)), color="#d62728", linewidth=1.4, zorder=1, label="Top 3 (PSV/Ajax/Fey)" if idx == 0 else None)

                    ax_h.set_yticks(y_positions)
                    ax_h.set_yticklabels(metrics_display)
                    ax_h.set_xlim(left=0, right=xmax)
                    ax_h.invert_yaxis()
                    ax_h.set_xlabel("Percentile (0–100)" if normalize_percentile else ("Per 96" if per96 else "Raw value"))
                    ax_h.set_title("Distribution by metric" + (" (percentile)" if normalize_percentile else ""))
                    ax_h.grid(axis='x', alpha=0.15)
                    for spine in ["top", "right", "left", "bottom"]:
                        ax_h.spines[spine].set_visible(False)
                    handles, labels_ = ax_h.get_legend_handles_labels()
                    if handles:
                        ax_h.legend(loc="lower right", frameon=False)
                    st.pyplot(fig_h, use_container_width=True)

                # Right: Radar plot
                with plot_cols[1]:
                    num_vars = len(radar_values)
                    angles = np.linspace(0, 2 * np.pi, num_vars, endpoint=False).tolist()
                    radar_plot_values = radar_values + radar_values[:1]
                    angles_plot = angles + angles[:1]

                    fig, ax = plt.subplots(subplot_kw=dict(polar=True), figsize=(6.5, 6.5))
                    ax.plot(angles_plot, radar_plot_values, color="#1f77b4", linewidth=2.5)
                    ax.fill(angles_plot, radar_plot_values, color="#1f77b4", alpha=0.25)
                    ax.set_theta_offset(np.pi / 2)
                    ax.set_theta_direction(-1)
                    ax.set_rlabel_position(0)
                    tick_labels = [f"{label}" for label in selected_labels]
                    ax.set_xticks(angles)
                    ax.set_xticklabels(tick_labels)
                    if normalize_percentile:
                        ax.set_ylim(0, 100)
                        ax.set_yticks([20, 40, 60, 80, 100])
                        ax.set_yticklabels(["20", "40", "60", "80", "100"]) 
                    ax.grid(alpha=0.2)
                    ax.set_title(f"{selected_player} - Radar{radar_suffix}")
                    st.pyplot(fig, use_container_width=True)

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

                    # Individual distribution plots per metric (true-value axes) - 2 per row
                    big3_teams = {"PSV", "Ajax", "Feyenoord"}
                    
                    # Create columns for 2 plots per row
                    plot_items = list(items)
                    for i in range(0, len(plot_items), 2):
                        cols = st.columns(2)
                        
                        for j, (label, key) in enumerate(plot_items[i:i+2]):
                            with cols[j]:
                                vals = distributions_local[key]
                                vmin = float(min(vals)) if vals else 0.0
                                vmax = float(max(vals)) if vals else 1.0
                                if vmax <= vmin:
                                    vmax = vmin + 1.0
                                
                                # Smaller, more compact figure
                                fig_m, ax_m = plt.subplots(figsize=(4, 2.2))
                                
                                # All dots for players in group
                                x_vals = [float(v) for v in vals]
                                ax_m.scatter(x_vals, [0] * len(x_vals), s=10, color="#8a8a8a", alpha=0.65, zorder=2)
                                
                                # Competition average
                                if vals:
                                    comp_avg = float(np.mean(x_vals))
                                    ax_m.vlines(comp_avg, -0.25, 0.25, linestyle=(0, (4, 4)), color="#4d4d4d", linewidth=1.2, zorder=1)
                                
                                # Top 3 average
                                big3_vals = []
                                for nm, p in group_players:
                                    team_name = str(p.get('team', '') or '')
                                    if any(t.lower() in team_name.lower() for t in big3_teams):
                                        big3_vals.append(value_per96(p, key))
                                if big3_vals:
                                    big3_avg = float(np.mean(big3_vals))
                                    ax_m.vlines(big3_avg, -0.25, 0.25, linestyle=(0, (2, 3)), color="#d62728", linewidth=1.2, zorder=1)
                                
                                # Selected player point
                                if sel_stats and sel_stats.get('position_group') == effective_group:
                                    sel_val = value_per96(sel_stats, key)
                                    ax_m.scatter([sel_val], [0], s=60, color="#1f77b4", edgecolor="white", linewidth=0.6, zorder=3)
                                
                                # Axes styling per metric - more compact
                                ax_m.set_title(label, fontsize=11, pad=8)
                                ax_m.set_yticks([])
                                
                                # Choose nice rounded ticks
                                rng = vmax - vmin
                                
                                # Calculate appropriate step size for nice ticks
                                if rng <= 0.1:
                                    step = 0.02
                                elif rng <= 0.5:
                                    step = 0.1
                                elif rng <= 1:
                                    step = 0.2
                                elif rng <= 2:
                                    step = 0.5
                                elif rng <= 5:
                                    step = 1.0
                                elif rng <= 10:
                                    step = 2.0
                                elif rng <= 20:
                                    step = 5.0
                                elif rng <= 50:
                                    step = 10.0
                                elif rng <= 100:
                                    step = 20.0
                                else:
                                    step = 50.0
                                
                                # Generate nice rounded ticks
                                # Start from a nice number below or at vmin
                                start_tick = step * np.floor(vmin / step)
                                if start_tick < vmin:
                                    start_tick += step
                                
                                # Generate ticks
                                ticks = []
                                current = start_tick
                                
                                # Special case: if range is 0-100 (percentage), don't go beyond 100
                                if vmin >= 0 and vmax <= 100 and rng >= 80:
                                    while current <= vmax:  # Stop at max for percentage ranges
                                        ticks.append(current)
                                        current += step
                                else:
                                    while current <= vmax:  # Stop at max for all ranges
                                        ticks.append(current)
                                        current += step
                                
                                # Remove ticks that are too far above max
                                ticks = [t for t in ticks if t <= vmax + step]
                                
                                ax_m.set_xlim(left=vmin, right=vmax)
                                ax_m.set_xticks(ticks)
                                ax_m.tick_params(axis='x', labelsize=9)
                                ax_m.grid(axis='x', alpha=0.15)
                                for spine in ["top", "right", "left", "bottom"]:
                                    ax_m.spines[spine].set_visible(False)
                                
                                st.pyplot(fig_m, use_container_width=True)

                # Render all backs groups
                for gname, items in backs_groups.items():
                    render_group_section(gname, items)
            else:
                st.info("Metric groups are currently only available for Backs. Select a back or the Backs group.")

        with dashboard2_tab:
            if selected_player_global:
                stats = valid_players[selected_player_global]
                position_group = stats.get('position_group', '')
                
                
                # Layout: top row with player info and radar chart, bottom row with line chart
                top_cols = st.columns([1, 2])
                bottom_cols = st.columns([3])
                
                # Top left: Player info and ratings
                with top_cols[0]:
                    # Player name with larger font
                    st.markdown(f"<h2 style='margin-bottom: 10px;'>{selected_player_global}</h2>", unsafe_allow_html=True)
                    st.markdown(f"**{stats.get('team', 'N/A')}**")
                    st.markdown(f"{stats.get('minutes_played', 0):.0f} minutes played")
                    st.markdown(f"**{stats.get('position', 'N/A')}**")
                    
                    # Performance scores (smaller, under general info)
                    if position_group == 'Backs':
                        st.markdown("---")
                        
                        group_metrics = backs_groups
                        
                        # Calculate all group scores first
                        group_scores = {}
                        group_players = [(name, p) for name, p in valid_players.items() 
                                       if p.get('position_group') == position_group]
                        
                        if group_players:
                            for group_name, items in group_metrics.items():
                                # Get distributions for this group
                                distributions_local = {}
                                
                                for _, key in items:
                                    vals = []
                                    for _, p in group_players:
                                        val = get_value_per96(p, key)
                                        vals.append(val)
                                    distributions_local[key] = vals
                                
                                # Calculate group rating using equal weights for all metrics
                                group_total = 0
                                group_count = 0
                                
                                for _, key in items:
                                    val = get_value_per96(stats, key)
                                    pct = calculate_percentile_rank(distributions_local[key], val)
                                    group_total += pct  # Equal weight (1.0) for all metrics
                                    group_count += 1
                                
                                group_rating = (group_total / group_count) if group_count > 0 else 50.0
                                group_rating = max(0.0, min(100.0, group_rating))
                                group_scores[group_name] = group_rating
                            
                            # Calculate overall score (average of all group scores)
                            overall_score = sum(group_scores.values()) / len(group_scores) if group_scores else 50.0
                            overall_score = max(0.0, min(100.0, overall_score))
                            
                            # Display overall score (smaller)
                            overall_color = _rating_color(overall_score)
                            st.markdown(f"""
                            <div style="background: {overall_color}; 
                                        color: white; padding: 20px; border-radius: 12px; text-align: center; 
                                        font-size: 28px; font-weight: bold; margin: 8px 0; 
                                        height: 80px; display: flex; align-items: center; justify-content: center;">
                                {overall_score:.1f}
                            </div>
                            """, unsafe_allow_html=True)
                            
                            # Display individual group scores (smaller)
                            for group_name, group_rating in group_scores.items():
                                group_color = _rating_color(group_rating)
                                st.markdown(f"""
                                <div style="background: {group_color}; 
                                            color: white; padding: 6px 10px; border-radius: 4px; text-align: center; 
                                            font-size: 16px; font-weight: bold; margin: 4px 0; padding: 8px 12px;">
                                    {group_name}: {group_rating:.1f}
                                </div>
                                """, unsafe_allow_html=True)
                
                # Top right: Radar chart with metrics colored by group
                with top_cols[1]:
                    if position_group == 'Backs':
                        
                        # Collect all metrics from all groups
                        all_metrics = []
                        group_colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b']
                        group_names = []
                        
                        for i, (group_name, items) in enumerate(backs_groups.items()):
                            for label, key in items:
                                all_metrics.append((label, key, group_name, group_colors[i % len(group_colors)]))
                                if group_name not in group_names:
                                    group_names.append(group_name)
                        
                        if all_metrics:
                            
                            # Calculate percentiles for radar chart
                            def calculate_percentile_rank(values, target_value):
                                if not values:
                                    return 50.0
                                sorted_values = sorted(values)
                                count_below = sum(1 for v in sorted_values if v < target_value)
                                count_equal = sum(1 for v in sorted_values if v == target_value)
                                total_count = len(sorted_values)
                                if total_count == 0:
                                    return 50.0
                                percentile = (count_below + 0.5 * count_equal) / total_count * 100
                                return max(0.0, min(100.0, percentile))
                            
                            # Get all players in the same position group for percentile calculation
                            group_players = [(name, p) for name, p in valid_players.items() 
                                           if p.get('position_group') == position_group]
                            
                            # Calculate percentiles for each metric
                            radar_values = []
                            radar_labels = []
                            metric_colors = []
                            
                            for label, key, group_name, color in all_metrics:
                                # Get all values for this metric in the position group
                                all_values = [get_value_per96(p, key) for _, p in group_players]
                                player_value = get_value_per96(stats, key)
                                percentile = calculate_percentile_rank(all_values, player_value)
                                
                                radar_values.append(percentile)
                                radar_labels.append(label)
                                metric_colors.append(color)
                            
                            # Create radar chart
                            num_vars = len(radar_values)
                            angles = np.linspace(0, 2 * np.pi, num_vars, endpoint=False).tolist()
                            radar_plot_values = radar_values + radar_values[:1]
                            angles_plot = angles + angles[:1]
                            
                            fig, ax = plt.subplots(subplot_kw=dict(polar=True), figsize=(2, 2))
                            
                            # Plot each metric with its group color
                            for i, (angle, value, color) in enumerate(zip(angles, radar_values, metric_colors)):
                                ax.plot([angle, angle], [0, value], color=color, linewidth=1, alpha=0.8)
                                ax.scatter([angle], [value], color=color, s=12, zorder=5)
                            
                            # Connect the dots
                            ax.plot(angles_plot, radar_plot_values, color='#333333', linewidth=0.3, alpha=0.3)
                            ax.fill(angles_plot, radar_plot_values, color='#333333', alpha=0.1)
                            
                            ax.set_theta_offset(np.pi / 2)
                            ax.set_theta_direction(-1)
                            ax.set_rlabel_position(0)
                            # Set proper y-axis limits for percentiles
                            ax.set_ylim(0, 100)
                            ax.set_xticks(angles)
                            ax.set_xticklabels(radar_labels, fontsize=4, fontweight='bold')
                            ax.set_yticks([20, 40, 60, 80, 100])
                            ax.set_yticklabels(["20", "40", "60", "80", "100"], fontsize=4)
                            # Keep the inner grid, remove only the outer circle
                            ax.grid(True, alpha=0.2)
                            
                            # Add legend for groups
                            legend_elements = [plt.Line2D([0], [0], color=group_colors[i % len(group_colors)], 
                                                        lw=1, label=group_name) for i, group_name in enumerate(group_names)]
                            ax.legend(handles=legend_elements, loc='upper center', bbox_to_anchor=(0.5, 1.25), 
                                     ncol=len(group_names), fontsize=3, frameon=False)
                            
                            st.pyplot(fig, use_container_width=True)
                        else:
                            st.info("No metrics available for radar chart")
                    else:
                        st.info("Radar chart only available for Backs position group")
                
                # Bottom: Line chart showing performance over matches
                with bottom_cols[0]:
                    if position_group == 'Backs':
                        
                        # Find all matches played by the selected player
                        player_matches = []
                        for i, match_data in enumerate(all_events_data):
                            # Extract events from match data
                            events = match_data.get('data', []) if isinstance(match_data, dict) else []
                            if not events:
                                continue
                                
                            # Check if player played in this match
                            player_minutes = calculate_player_minutes(events)
                            if selected_player_global in player_minutes and player_minutes[selected_player_global] > 0:
                                # Get match name from filename
                                if i < len(file_names):
                                    match_file = file_names[i]
                                    home_team, away_team, date = parse_teams_from_filename(match_file)
                                    match_name = f"{home_team} vs {away_team}" if home_team and away_team else f"Match {i+1}"
                                else:
                                    match_name = f"Match {i+1}"
                                player_matches.append((match_name, "Unknown", events))
                        
                        if player_matches:
                            # Sort matches by date
                            player_matches.sort(key=lambda x: x[1])
                            
                            # Calculate group scores for each match
                            match_scores = []
                            match_names = []
                            
                            # Pre-calculate all players' per-96 stats for the season (for comparison)
                            season_per96_stats = {}
                            for pname, pstats in valid_players.items():
                                if pstats.get('position_group') == position_group:
                                    season_per96_stats[pname] = {}
                                    for group_name, items in backs_groups.items():
                                        for _, key in items:
                                            season_per96_stats[pname][key] = get_value_per96(pstats, key)
                            
                            for match_name, date, events in player_matches:
                                # Calculate player stats for this specific match
                                match_stats = calculate_match_stats(events, selected_player_global)
                                
                                if match_stats:
                                    # Determine opponent team and home/away status
                                    player_team = stats.get('team', '')
                                    opponent_name = "Opponent"
                                    is_home = True
                                    
                                    # Parse match name to find opponent and determine home/away
                                    if " vs " in match_name:
                                        home_team, away_team = match_name.split(" vs ")
                                        if home_team == player_team:
                                            opponent_name = away_team
                                            is_home = True  # Player's team is home
                                        elif away_team == player_team:
                                            opponent_name = home_team
                                            is_home = False  # Player's team is away
                                        else:
                                            # If player team not found, use the other team
                                            opponent_name = away_team if home_team == player_team else home_team
                                            is_home = home_team == player_team
                                    
                                    group_scores = {}
                                    
                                    for group_name, items in backs_groups.items():
                                        group_total = 0
                                        group_count = 0
                                        
                                        for _, key in items:
                                            val = match_stats.get(key, 0.0)
                                            
                                            # Calculate percentile rank for this metric across all players in the season
                                            all_values = []
                                            for pname, pstats in season_per96_stats.items():
                                                all_values.append(pstats.get(key, 0.0))
                                            
                                            if all_values:
                                                pct = calculate_percentile_rank(all_values, val)
                                                group_total += pct
                                                group_count += 1
                                        
                                        group_rating = (group_total / group_count) if group_count > 0 else 50.0
                                        group_scores[group_name] = group_rating
                                    
                                    # Overall score for this match
                                    overall_score = sum(group_scores.values()) / len(group_scores) if group_scores else 50.0
                                    
                                    match_scores.append(overall_score)
                                    # Add (T) for home matches, (U) for away matches
                                    home_away_indicator = "(T)" if is_home else "(U)"
                                    match_names.append(f"{opponent_name} {home_away_indicator}")
                            
                            # Create line chart
                            if match_scores:
                                fig_line, ax_line = plt.subplots(figsize=(35, 5))
                                
                                # Plot the line
                                ax_line.plot(range(len(match_scores)), match_scores, 
                                           marker='o', linewidth=3, markersize=8, color='#1f77b4')
                                
                                # Style the chart
                                
                                ax_line.grid(True, alpha=0.3)
                                
                                # Set x-axis labels
                                ax_line.set_xticks(range(len(match_names)))
                                ax_line.set_xticklabels(match_names, fontsize=16, fontweight='bold')
                                
                                # Set y-axis limits and labels
                                ax_line.set_ylim(0, 100)
                                ax_line.set_ylabel('Overall Score', fontsize=18, fontweight='bold')
                                ax_line.tick_params(axis='y', labelsize=16)
                                
                                plt.tight_layout()
                                st.pyplot(fig_line, use_container_width=True)
                                
                                # Add table with all players in position group
                                st.markdown("**Position Group Rankings**")
                                
                                # Create table data
                                table_data = []
                                for pname, pstats in valid_players.items():
                                    if pstats.get('position_group') == position_group:
                                        # Calculate overall score for this player
                                        player_group_scores = {}
                                        for group_name, items in backs_groups.items():
                                            group_total = 0
                                            group_count = 0
                                            
                                            for _, key in items:
                                                val = get_value_per96(pstats, key)
                                                # Calculate percentile rank for this metric
                                                all_values = []
                                                for other_pname, other_pstats in valid_players.items():
                                                    if other_pstats.get('position_group') == position_group:
                                                        all_values.append(get_value_per96(other_pstats, key))
                                                
                                                if all_values:
                                                    pct = calculate_percentile_rank(all_values, val)
                                                    group_total += pct
                                                    group_count += 1
                                            
                                            group_rating = (group_total / group_count) if group_count > 0 else 50.0
                                            player_group_scores[group_name] = group_rating
                                        
                                        # Overall score
                                        overall_score = sum(player_group_scores.values()) / len(player_group_scores) if player_group_scores else 50.0
                                        
                                        # Add to table
                                        row = {
                                            'Player': pname,
                                            'Team': pstats.get('team', ''),
                                            'Minutes': f"{pstats.get('minutes_played', 0):.0f}",
                                            'Overall': f"{overall_score:.1f}",
                                        }
                                        
                                        # Add individual group scores
                                        for group_name, score in player_group_scores.items():
                                            row[group_name] = f"{score:.1f}"
                                        
                                        table_data.append(row)
                                
                                # Sort by overall score (descending)
                                table_data.sort(key=lambda x: float(x['Overall']), reverse=True)
                                
                                # Display table
                                if table_data:
                                    st.dataframe(table_data, use_container_width=True)
                                else:
                                    st.info("No players found in this position group")
                                    
                            else:
                                st.info("No match data available for line chart")
                        else:
                            st.info("Line chart only available for Backs position group")
                    else:
                        st.info("Line chart only available for Backs position group")
                
            else:
                st.info("Please select a player to view Dashboard2")