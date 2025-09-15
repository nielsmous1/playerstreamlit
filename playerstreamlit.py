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
if os.path.exists(match_folder):
    json_files = sorted([p for p in Path(match_folder).glob("*.json")])
    for p in json_files:
        try:
            events_data = load_json_lenient(str(p))
            if events_data:
                all_events_data.append(events_data)
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

        # Function to find all goalkeeper events (saves and unsuccessful saves)
        def find_goalkeeper_events(events):
            gk_events = []
            for event in events:
                # Check for save events (baseTypeId 12)
                if event.get('baseTypeId') == 12:  # KEEPER_SAVE
                    gk_name = event.get('playerName', 'Unknown')
                    if gk_name and gk_name != 'Unknown':
                        result_id = event.get('resultId', 1)
                        is_successful = result_id == 1  # 1 = SUCCESSFUL, 0 = UNSUCCESSFUL
                        
                        save_info = {
                            'team': event.get('teamName', 'Unknown'),
                            'goalkeeper': gk_name,
                            'xs': event.get('metrics', {}).get('xS', 0.0),
                            'psxg': event.get('metrics', {}).get('PSxG', 0.0),
                            'is_save': is_successful,
                            'is_unsuccessful_save': not is_successful,
                            'time': int((event.get('startTimeMs', 0) or 0) / 1000 / 60),
                            'partId': event.get('partId', 1)
                        }
                        gk_events.append(save_info)
                
            return gk_events

        # Get all shot events, dribble events, and goalkeeper events
        all_shots = find_shot_events(all_events)
        all_dribbles = find_dribble_events(all_events)
        all_gk_events = find_goalkeeper_events(all_events)
        
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
                    'goals_prevented': 0.0,
                    'psxg_faced': 0.0,
                    'goals_allowed': 0,
                    'minutes_played': total_player_minutes.get(player_name, 0)
                }
            
            # Add goal progression (negative means closer to goal, so we add the negative value)
            goal_progression = dribble['goal_progression']
            if goal_progression < 0:  # Negative means progression toward goal
                player_stats[player_name]['pbd'] += abs(goal_progression)
        
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
        
        # Sort players by xG (descending)
        sorted_players = sorted(player_stats.items(), key=lambda x: x[1]['xG'], reverse=True)
        
        # Create tabs for different views
        tab1, tab2 = st.tabs(["Player Performance Analysis", "Goalkeeper Save Analysis"])
        
        with tab1:
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
                    max_value=180,
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
                        goals_prevented_display = f"{stats['goals_prevented'] * multiplier:.2f}"
                        psxg_faced_display = f"{stats['psxg_faced'] * multiplier:.2f}"
                        goals_allowed_display = f"{stats['goals_allowed'] * multiplier:.1f}"
                    else:
                        xg_display = f"{stats['xG']:.3f}"
                        psxg_display = f"{stats['PSxG']:.3f}"
                        psxg_minus_xg_display = f"{stats['PSxG_minus_xG']:.3f}"
                        shots_display = f"{stats['shots']:.0f}"
                        pbd_display = f"{stats['pbd']:.1f}"
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
        
        with tab2:
            st.subheader("Goalkeeper Save Analysis")
            
            # Get all goalkeepers who have faced shots
            goalkeepers = [name for name, stats in player_stats.items() if stats['psxg_faced'] > 0]
            
            if goalkeepers:
                # Player selector
                selected_goalkeeper = st.selectbox(
                    "Select Goalkeeper:",
                    options=goalkeepers,
                    index=0
                )
                
                # Get unsuccessful saves for selected goalkeeper
                unsuccessful_saves = []
                for gk_event in all_gk_events:
                    if (gk_event.get('goalkeeper') == selected_goalkeeper and 
                        gk_event.get('is_unsuccessful_save', False)):
                        unsuccessful_saves.append(gk_event)
                
                if unsuccessful_saves:
                    st.write(f"**{selected_goalkeeper} - Unsuccessful Saves:**")
                    st.write(f"Total: {len(unsuccessful_saves)} unsuccessful saves")
                    
                    # Create table with unsuccessful saves details
                    save_data = []
                    for i, save in enumerate(unsuccessful_saves, 1):
                        # Try to determine which match this save came from and find opponent team
                        match_info = f"Match {i}"
                        opponent_team = "Unknown"
                        
                        for match_idx, events_data in enumerate(all_events_data, 1):
                            events = events_data.get('data', []) if isinstance(events_data, dict) else []
                            for event in events:
                                if (event.get('baseTypeId') == 12 and 
                                    event.get('playerName') == selected_goalkeeper and
                                    abs(event.get('startTimeMs', 0) - save['time'] * 60 * 1000) < 1000 and  # Within 1 second
                                    event.get('partId') == save['partId']):
                                    match_info = f"Match {match_idx}"
                                    
                                    # Find the opponent team by looking for shot events around the same time
                                    for shot_event in events:
                                        if (shot_event.get('baseTypeId') in [9, 10] and  # Shot or Goal events
                                            abs(shot_event.get('startTimeMs', 0) - save['time'] * 60 * 1000) < 2000 and  # Within 2 seconds
                                            shot_event.get('partId') == save['partId'] and
                                            shot_event.get('teamName') != save['team']):  # Different team than goalkeeper's team
                                            opponent_team = shot_event.get('teamName', 'Unknown')
                                            break
                                    break
                            if match_info != f"Match {i}":
                                break
                        
                        save_data.append({
                            'Save #': i,
                            'Match': match_info,
                            'Minute': f"{save['time']:.0f}'",
                            'Part': f"Part {save['partId']}",
                            'xS': f"{save['xs']:.3f}",
                            'PSxG': f"{1.0 - save['xs']:.3f}",
                            'Opponent': opponent_team
                        })
                    
                    # Display the table
                    st.dataframe(
                        save_data,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Save #": st.column_config.NumberColumn("Save #", width="small"),
                            "Match": st.column_config.TextColumn("Match", width="medium"),
                            "Minute": st.column_config.TextColumn("Minute", width="small"),
                            "Part": st.column_config.TextColumn("Part", width="small"),
                            "xS": st.column_config.NumberColumn("xS", width="small", format="%.3f"),
                            "PSxG": st.column_config.NumberColumn("PSxG", width="small", format="%.3f"),
                            "Opponent": st.column_config.TextColumn("Opponent", width="small")
                        }
                    )
                else:
                    st.info(f"No unsuccessful saves found for {selected_goalkeeper}.")
            else:
                st.info("No goalkeepers found in the data.")