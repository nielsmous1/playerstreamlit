import streamlit as st
import json
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import matplotlib.gridspec as gridspec
from matplotlib.patches import Rectangle
import os
from pathlib import Path

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
        all_takeons = find_takeon_events(all_events)
        all_passes_to_box = find_passes_to_box_events(all_events)
        all_counter_pressures = find_counter_pressure_events(all_events)
        all_gk_events = find_goalkeeper_events(all_events)
        
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
        
        # Process shots
        for shot in all_shots:
            player_name = shot['player']
            if player_name not in player_stats:
                player_stats[player_name] = {
                    'team': shot['team'],
                    'xG': 0.0,
                    'PSxG': 0.0,
                    'shots': 0,
                    'pbd': 0.0,
                    'takeons': 0,
                    'takeons_total': 0,
                    'passes_to_box': 0,
                    'counter_pressures': 0,
                    'goals_prevented': 0.0,
                    'psxg_faced': 0.0,
                    'goals_allowed': 0,
                    'minutes_played': total_player_minutes.get(player_name, 0)
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
                    'PSxG': 0.0,
                    'shots': 0,
                    'pbd': 0.0,
                    'takeons': 0,
                    'takeons_total': 0,
                    'passes_to_box': 0,
                    'counter_pressures': 0,
                    'goals_prevented': 0.0,
                    'psxg_faced': 0.0,
                    'goals_allowed': 0,
                    'minutes_played': total_player_minutes.get(player_name, 0)
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
                    'PSxG': 0.0,
                    'shots': 0,
                    'pbd': 0.0,
                    'takeons': 0,
                    'takeons_total': 0,
                    'passes_to_box': 0,
                    'counter_pressures': 0,
                    'goals_prevented': 0.0,
                    'psxg_faced': 0.0,
                    'goals_allowed': 0,
                    'minutes_played': total_player_minutes.get(player_name, 0)
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
                    'PSxG': 0.0,
                    'shots': 0,
                    'pbd': 0.0,
                    'takeons': 0,
                    'takeons_total': 0,
                    'passes_to_box': 0,
                    'counter_pressures': 0,
                    'goals_prevented': 0.0,
                    'psxg_faced': 0.0,
                    'goals_allowed': 0,
                    'minutes_played': total_player_minutes.get(player_name, 0)
                }
            
            # Count successful passes to box
            player_stats[player_name]['passes_to_box'] += 1
        
        # Process counter pressures
        for pressure_event in all_counter_pressures:
            player_name = pressure_event['player']
            if player_name not in player_stats:
                player_stats[player_name] = {
                    'team': pressure_event['team'],
                    'xG': 0.0,
                    'PSxG': 0.0,
                    'shots': 0,
                    'pbd': 0.0,
                    'takeons': 0,
                    'takeons_total': 0,
                    'passes_to_box': 0,
                    'counter_pressures': 0,
                    'goals_prevented': 0.0,
                    'psxg_faced': 0.0,
                    'goals_allowed': 0,
                    'minutes_played': total_player_minutes.get(player_name, 0)
                }
            
            # Count counter pressures
            player_stats[player_name]['counter_pressures'] += 1
        
        # Process goalkeeper events for GK performance calculation
        for gk_event in all_gk_events:
            gk_name = gk_event['goalkeeper']
            if gk_name not in player_stats:
                player_stats[gk_name] = {
                    'team': gk_event['team'],
                    'xG': 0.0,
                    'PSxG': 0.0,
                    'shots': 0,
                    'pbd': 0.0,
                    'takeons': 0,
                    'takeons_total': 0,
                    'passes_to_box': 0,
                    'counter_pressures': 0,
                    'goals_prevented': 0.0,
                    'psxg_faced': 0.0,
                    'goals_allowed': 0,
                    'minutes_played': total_player_minutes.get(gk_name, 0)
                }
            
            # Add PSxG faced for all save attempts (both successful and unsuccessful)
            # PSxG faced = 1 - xS for each save attempt
            player_stats[gk_name]['psxg_faced'] += (1.0 - gk_event['xs'])
        
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
        
        analysis_tab, dashboard_tab = st.tabs(["Analysis", "Dashboard"])

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
                        psxg_display = f"{stats['PSxG'] * multiplier:.3f}"
                        psxg_minus_xg_display = f"{stats['PSxG_minus_xG'] * multiplier:.3f}"
                        shots_display = f"{stats['shots'] * multiplier:.1f}"
                        pbd_display = f"{stats['pbd'] * multiplier:.1f}"
                        takeons_display = f"{stats['takeons'] * multiplier:.1f}"
                        takeon_success_pct_display = f"{stats['takeon_success_pct']:.1f}%"
                        passes_to_box_display = f"{stats['passes_to_box'] * multiplier:.1f}"
                        counter_pressures_display = f"{stats['counter_pressures'] * multiplier:.1f}"
                        goals_prevented_display = f"{stats['goals_prevented'] * multiplier:.2f}"
                        psxg_faced_display = f"{stats['psxg_faced'] * multiplier:.2f}"
                        goals_allowed_display = f"{stats['goals_allowed'] * multiplier:.1f}"
                    else:
                        xg_display = f"{stats['xG']:.3f}"
                        psxg_display = f"{stats['PSxG']:.3f}"
                        psxg_minus_xg_display = f"{stats['PSxG_minus_xG']:.3f}"
                        shots_display = f"{stats['shots']:.0f}"
                        pbd_display = f"{stats['pbd']:.1f}"
                        takeons_display = f"{stats['takeons']:.0f}"
                        takeon_success_pct_display = f"{stats['takeon_success_pct']:.1f}%"
                        passes_to_box_display = f"{stats['passes_to_box']:.0f}"
                        counter_pressures_display = f"{stats['counter_pressures']:.0f}"
                        goals_prevented_display = f"{stats['goals_prevented']:.2f}"
                        psxg_faced_display = f"{stats['psxg_faced']:.2f}"
                        goals_allowed_display = f"{stats['goals_allowed']:.0f}"
                    
                    table_data.append({
                        'Rank': i + 1,
                        'Player': player_name,
                        'Team': stats['team'],
                        'Minutes': f"{stats['minutes_played']:.0f}",
                        'xG': xg_display,
                        'PSxG': psxg_display,
                        'PSxG - xG': psxg_minus_xg_display,
                        'PBD': pbd_display,
                        'Take-ons': takeons_display,
                        'Take-on %': takeon_success_pct_display,
                        'Passes to Box': passes_to_box_display,
                        'Counter Pressures': counter_pressures_display,
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
                        "Minutes": st.column_config.NumberColumn("Minutes", width="small"),
                        "xG": st.column_config.NumberColumn("xG", width="small", format="%.3f"),
                        "PSxG": st.column_config.NumberColumn("PSxG", width="small", format="%.3f"),
                        "PSxG - xG": st.column_config.NumberColumn("PSxG - xG", width="small", format="%.3f"),
                        "PBD": st.column_config.NumberColumn("PBD", width="small", format="%.1f", help="Progression By Dribble (meters)"),
                        "Take-ons": st.column_config.NumberColumn("Take-ons", width="small", format="%.0f", help="Successful take-ons (label 121)"),
                        "Take-on %": st.column_config.TextColumn("Take-on %", width="small", help="Take-on success percentage"),
                        "Passes to Box": st.column_config.NumberColumn("Passes to Box", width="small", format="%.0f", help="Successful passes to box (label 72)"),
                        "Counter Pressures": st.column_config.NumberColumn("Counter Pressures", width="small", format="%.0f", help="Counter pressure actions (label 215)"),
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

            # Player selector
            with dashboard_cols[0]:
                player_options = sorted(list(valid_players.keys()))
                selected_player = st.selectbox("Select player", options=player_options)

            # Show standard info
            if selected_player:
                stats = valid_players[selected_player]
                with dashboard_cols[1]:
                    st.metric("Team", stats['team'])
                    st.metric("Minutes Played", f"{stats['minutes_played']:.0f}")

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
                per96 = st.checkbox("Per 96 minutes", value=False, help="Normalize selected player's stats to 96 minutes")
                normalize = st.checkbox("Normalize 0-1 across players", value=True, help="Scale each metric by the max across all players")

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
                player_values = [get_value(selected_stats, k) for k in chosen_keys]

                # Normalization by field max (shared for both charts)
                if normalize:
                    max_values = []
                    for key in chosen_keys:
                        vals = []
                        for _, p in valid_players.items():
                            v = get_value(p, key)
                            vals.append(abs(v) if key in ['PSxG_minus_xG'] else v)
                        max_v = max(vals) if vals else 1.0
                        if max_v == 0:
                            max_v = 1.0
                        max_values.append(max_v)
                    norm_values = []
                    for v, m, k in zip(player_values, max_values, chosen_keys):
                        value = abs(v) if k in ['PSxG_minus_xG'] else v
                        norm_values.append(value / m if m else 0.0)
                    radar_values = norm_values
                    radar_suffix = " (0-1)"
                else:
                    radar_values = player_values
                    radar_suffix = ""

                plot_cols = st.columns([3, 4])

                # Left: horizontal bar with all players' dots per metric
                with plot_cols[0]:
                    fig_h, ax_h = plt.subplots(figsize=(7, 6 + max(0, len(chosen_keys) - 5) * 0.4))
                    metrics_display = list(reversed(selected_labels))
                    keys_display = list(reversed(chosen_keys))
                    y_positions = np.arange(len(keys_display))

                    # Precompute per-metric scales, averages, and values
                    big3_teams = {"PSV", "Ajax", "Feyenoord"}
                    for idx, (label, key) in enumerate(zip(metrics_display, keys_display)):
                        # All players' values for this metric
                        values_all = []
                        values_all_for_max = []
                        big3_values = []
                        for name, p in valid_players.items():
                            v = get_value(p, key)
                            # For normalization mirroring
                            if normalize:
                                m = max_values[len(chosen_keys) - 1 - idx]  # reversed index
                                vv = (abs(v) if key in ['PSxG_minus_xG'] else v) / m if m else 0.0
                            else:
                                vv = v
                            values_all.append(vv)
                            values_all_for_max.append(vv)
                            team_name = str(p.get('team', '') or '')
                            if any(t.lower() in team_name.lower() for t in big3_teams):
                                big3_values.append(vv)

                        # Scales
                        if normalize:
                            xmax = 1.0
                        else:
                            xmax = max(values_all_for_max) if values_all_for_max else 1.0
                            if xmax == 0:
                                xmax = 1.0

                        y = y_positions[idx]
                        # Background bar
                        ax_h.barh(y, xmax, color="#f0f0f0", edgecolor="none", height=0.6, zorder=1)

                        # All players small grey dots
                        ax_h.scatter(values_all, np.full(len(values_all), y), s=12, color="#777777", alpha=0.7, zorder=2)

                        # Selected player value
                        sel_v_raw = get_value(selected_stats, key)
                        if normalize:
                            msel = max_values[len(chosen_keys) - 1 - idx]
                            sel_v = (abs(sel_v_raw) if key in ['PSxG_minus_xG'] else sel_v_raw) / msel if msel else 0.0
                        else:
                            sel_v = sel_v_raw
                        ax_h.scatter([sel_v], [y], s=50, color="#1f77b4", edgecolor="white", linewidth=0.8, zorder=3, label="Selected player" if idx == 0 else None)

                        # Averages
                        if values_all:
                            avg = float(np.mean(values_all))
                            ax_h.axvline(avg, linestyle=(0, (4, 4)), color="#333333", linewidth=1.2, zorder=1, label="Average" if idx == 0 else None)
                        if big3_values:
                            avg_big3 = float(np.mean(big3_values))
                            ax_h.axvline(avg_big3, linestyle=(0, (2, 3)), color="#d62728", linewidth=1.2, zorder=1, label="Top 3 (PSV/Ajax/Fey)" if idx == 0 else None)

                    ax_h.set_yticks(y_positions)
                    ax_h.set_yticklabels(metrics_display)
                    ax_h.set_xlim(left=0)
                    ax_h.invert_yaxis()
                    ax_h.set_xlabel("Per 96" if per96 else "Raw value")
                    ax_h.set_title("Distribution by metric" + (" (0-1)" if normalize else ""))
                    handles, labels_ = ax_h.get_legend_handles_labels()
                    if handles:
                        ax_h.legend(loc="lower right")
                    st.pyplot(fig_h, use_container_width=True)

                # Right: Radar plot
                with plot_cols[1]:
                    num_vars = len(radar_values)
                    angles = np.linspace(0, 2 * np.pi, num_vars, endpoint=False).tolist()
                    radar_plot_values = radar_values + radar_values[:1]
                    angles_plot = angles + angles[:1]

                    fig, ax = plt.subplots(subplot_kw=dict(polar=True), figsize=(6, 6))
                    ax.plot(angles_plot, radar_plot_values, color="#1f77b4", linewidth=2)
                    ax.fill(angles_plot, radar_plot_values, color="#1f77b4", alpha=0.2)
                    ax.set_theta_offset(np.pi / 2)
                    ax.set_theta_direction(-1)
                    ax.set_rlabel_position(0)
                    tick_labels = [f"{label}" for label in selected_labels]
                    ax.set_xticks(angles)
                    ax.set_xticklabels(tick_labels)
                    ax.set_title(f"{selected_player} - Radar{radar_suffix}")
                    st.pyplot(fig, use_container_width=True)