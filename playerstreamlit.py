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

        # Get all shot events
        all_shots = find_shot_events(all_events)
        
        # Calculate player statistics
        player_stats = {}
        for shot in all_shots:
            player_name = shot['player']
            if player_name not in player_stats:
                player_stats[player_name] = {
                    'team': shot['team'],
                    'xG': 0.0,
                    'PSxG': 0.0,
                    'shots': 0
                }
            
            player_stats[player_name]['xG'] += shot['xG']
            player_stats[player_name]['shots'] += 1
            if shot['PSxG'] is not None:
                player_stats[player_name]['PSxG'] += shot['PSxG']
        
        # Calculate PSxG - xG for each player
        for player in player_stats:
            player_stats[player]['PSxG_minus_xG'] = player_stats[player]['PSxG'] - player_stats[player]['xG']
        
        # Sort players by xG (descending)
        sorted_players = sorted(player_stats.items(), key=lambda x: x[1]['xG'], reverse=True)
        
        # Player selector
        st.subheader("Player Performance Analysis")
        col1, col2 = st.columns([1, 3])
        
        with col1:
            num_players = st.selectbox(
                "Number of players to show:",
                options=[10, 20, 50, 100, len(sorted_players)],
                index=0
            )
        
        with col2:
            st.write(f"Showing top {min(num_players, len(sorted_players))} players by xG")
        
        # Create player table
        if sorted_players:
            # Prepare data for the table
            table_data = []
            for i, (player_name, stats) in enumerate(sorted_players[:num_players]):
                table_data.append({
                    'Rank': i + 1,
                    'Player': player_name,
                    'Team': stats['team'],
                    'xG': f"{stats['xG']:.3f}",
                    'PSxG': f"{stats['PSxG']:.3f}",
                    'PSxG - xG': f"{stats['PSxG_minus_xG']:.3f}",
                    'Shots': stats['shots']
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
                    "xG": st.column_config.NumberColumn("xG", width="small", format="%.3f"),
                    "PSxG": st.column_config.NumberColumn("PSxG", width="small", format="%.3f"),
                    "PSxG - xG": st.column_config.NumberColumn("PSxG - xG", width="small", format="%.3f"),
                    "Shots": st.column_config.NumberColumn("Shots", width="small")
                }
            )
        else:
            st.info("No shot data found for player analysis.")