import streamlit as st
import json
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import matplotlib.gridspec as gridspec
from matplotlib.patches import Rectangle
import matplotlib.image as mpimg
import os
from pathlib import Path

# Page config
st.set_page_config(page_title="Match Control Analysis", layout="wide")

# Initialize session state for colors
if 'home_color' not in st.session_state:
    st.session_state.home_color = '#1f77b4'
if 'away_color' not in st.session_state:
    st.session_state.away_color = '#ff7f0e'

# Title
st.title("Eredivisie 2025/2026 Data-Analyse")

# Sidebar for appearance
with st.sidebar:
    col1, col2 = st.columns(2)
    with col1:
        st.session_state.home_color = st.color_picker("Kleur Thuis", 
                                                      st.session_state.home_color)
    with col2:
        st.session_state.away_color = st.color_picker("Kleur Uit", 
                                                      st.session_state.away_color)

# Main screen: folder-only selection with team and match dropdowns
events_data = None
file_name = None

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

available_teams = {}
files_info = []  # list of dicts: {path, name, home, away, date, label}

if os.path.exists(match_folder):
    json_files = sorted([p for p in Path(match_folder).glob("*.json")])
    for p in json_files:
        home, away, yyyymmdd = parse_teams_from_filename(p.name)
        # Only use filename-derived teams to avoid partial tokens from metadata
        # Build friendly label like: "Home - Away DD-MM-YYYY"
        label = p.name
        if home and away and yyyymmdd and len(yyyymmdd) == 8:
            dd = yyyymmdd[6:8]
            mm = yyyymmdd[4:6]
            yyyy = yyyymmdd[0:4]
            label = f"{home} - {away}, {dd}-{mm}-{yyyy}"
        # Build canonical team map (case-insensitive dedupe)
        if home:
            key = home.strip().lower()
            if key not in available_teams:
                available_teams[key] = home
        if away:
            key = away.strip().lower()
            if key not in available_teams:
                available_teams[key] = away
        files_info.append({
            'path': str(p),
            'name': p.name,
            'home': home,
            'away': away,
            'date': yyyymmdd,
            'label': label
        })
else:
    st.warning("Folder not found")

selected_team = None
selected_match = None

if available_teams:
    team_options = sorted(available_teams.values(), key=lambda s: s.lower())
    selected_team = st.selectbox("Selecteer een team", team_options)
    team_matches = []
    if selected_team:
        for info in files_info:
            if (
                (info['home'] and info['home'].strip().lower() == selected_team.strip().lower()) or
                (info['away'] and info['away'].strip().lower() == selected_team.strip().lower())
            ):
                team_matches.append(info)
        # Build friendly labels
        match_labels = [info['label'] for info in team_matches]
        if match_labels:
            choice = st.selectbox("Selecteer een wedstrijd", match_labels)
            if choice:
                sel = next((i for i in team_matches if i['label'] == choice), None)
                if sel:
                    file_name = sel['name']
                    try:
                        events_data = load_json_lenient(sel['path'])
                    except Exception as e:
                        st.error(f"Failed to load JSON: {e}")
                        events_data = None
        else:
            st.info("No matches found for the selected team in this folder.")
else:
    st.info("No JSON files found in the specified folder")

# Load custom icons unconditionally (relative to repo)
try:
    icons_dir = BASE_DIR / "icons"
    ball_icon_path = icons_dir / "football.png"
    sub_icon_path = icons_dir / "subicon.png"
    redcard_icon_path = icons_dir / "red_card.png"
    ball_icon = mpimg.imread(str(ball_icon_path))
    sub_icon = mpimg.imread(str(sub_icon_path))
    redcard_icon = mpimg.imread(str(redcard_icon_path))
except Exception:
    st.warning("Icon files not found in './icons'. Using default markers.")
    ball_icon = None
    sub_icon = None
    redcard_icon = None

def load_team_logo(team_name):
    """Load team logo from logos folder"""
    try:
        logos_dir = BASE_DIR / "logos"
        logo_path = logos_dir / f"{team_name}.png"
        
        if logo_path.exists():
            return mpimg.imread(str(logo_path))
        
        return None
    except Exception:
        return None

# Make colors available globally for the function
home_color = st.session_state.home_color
away_color = st.session_state.away_color

def calculate_game_control_and_domination(data, home_team_override=None, away_team_override=None):
    """
    Calculate both game control (possession metrics) and domination (threat creation).
    
    Control: Shown as filled areas with outline - includes successful passes,
             final third passes, interceptions, tackles, dribbles, and recoveries.
    Domination: Shown as dashed lines in team colors - includes goals, shots, and
                dangerous passes to/in box with xG incorporated.
    """
    
    # Handle different data structures
    if isinstance(data, dict) and 'data' in data:
        events = data['data']
    elif isinstance(data, dict) and 'events' in data:
        events = data['events']
    elif isinstance(data, list):
        events = data
    else:
        events = []
        if isinstance(data, dict):
            for v in data.values():
                if isinstance(v, list):
                    events = v
                    break
    
    # Get team names from metadata if present
    home_team = home_team_override
    away_team = away_team_override
    
    if home_team is None or away_team is None:
        if isinstance(data, dict) and 'metaData' in data and isinstance(data['metaData'], dict):
            metadata = data['metaData']
            home_meta = metadata.get('homeTeamName') or metadata.get('homeTeam') or metadata.get('home')
            away_meta = metadata.get('awayTeamName') or metadata.get('awayTeam') or metadata.get('away')
            
            if home_team is None and home_meta:
                home_team = home_meta
            if away_team is None and away_meta:
                away_team = away_meta
    
    # Normalized team strings for matching
    def _norm(s):
        return s.lower().strip() if isinstance(s, str) else ''
    
    home_norm = _norm(home_team)
    away_norm = _norm(away_team)
    
    # DOMINATION weights (threat/danger creation)
    DOMINATION_WEIGHTS = {
        'GOAL': 8,
        'SHOT_ON_TARGET': 8,
        'SHOT_POST': 6,
        'INTERCEPTION_FINAL_THIRD': 5,
        'PASS_TO_BOX': 4,
        'SHOT_BLOCKED': 3,
        'PASS_IN_BOX': 5,
        'SHOT_WIDE': 3,
        'DRIBBLE_TO_BOX': 4,
        'XG_MULTIPLIER': 20
    }
    
    # CONTROL weights (possession/ball control)
    CONTROL_WEIGHTS = {
        'PASS_KEY': 2.5,
        'PASS_TO_FINAL_THIRD': 2,
        'PASS_IN_FINAL_THIRD': 2.5,
        'INTERCEPTION': 2,
        'DRIBBLE_SUCCESSFUL': 2.5,
        'COUNTER_INTERCEPTION': 2.5,
    }
    
    # SciSports type mappings
    BASE_TYPE = {
        'PASS': 1,
        'DRIBBLE': 2,
        'TACKLE': 3,
        'INTERCEPTION': 5,
        'SHOT': 6,
        'BALL_RECOVERY': 9,
        'PERIOD': 14,
        'SUBSTITUTE': 16,
    }
    
    SUB_TYPE = {
        'OWN_GOAL': 1101,
        'END_PERIOD': 1401,
        'START_PERIOD': 1400,
        'SUBBED_OUT': 1600,
        'SUBBED_IN': 1601,
        'KEY_PASS': 101,
        'COUNTER_INTERCEPTION': 196,
    }
    
    RESULT = {
        'UNSUCCESSFUL': 0,
        'SUCCESSFUL': 1,
    }
    
    SHOT_TYPE = {
        'WIDE': 1,
        'POST': 2,
        'ON_TARGET': 3,
        'BLOCKED': 4,
    }
    
    # Helper to match team
    def match_event_team(event_team_str):
        team_norm = _norm(event_team_str)
        if not team_norm:
            return None
        
        if home_norm and (home_norm in team_norm or team_norm in home_norm):
            return home_team
        if away_norm and (away_norm in team_norm or team_norm in away_norm):
            return away_team
        
        if home_norm and any(part in team_norm for part in home_norm.split()):
            return home_team
        if away_norm and any(part in team_norm for part in away_norm.split()):
            return away_team
        
        return None
    
    # Initialize event lists
    first_half_domination_events = []
    first_half_control_events = []
    second_half_domination_events = []
    second_half_control_events = []
    first_half_goals = []
    second_half_goals = []
    first_half_subs = []
    second_half_subs = []
    first_half_cards = []
    second_half_cards = []
    
    # Process events
    for event in events:
        team_field = event.get('teamName') or event.get('team') or event.get('team_name') or event.get('teamNameFormatted')
        matched_team = match_event_team(team_field)
        
        if matched_team is None:
            continue
        
        team = matched_team
        
        base_type_id = event.get('baseTypeId')
        sub_type_id = event.get('subTypeId')
        result_id = event.get('resultId')
        shot_type_id = event.get('shotTypeId')
        
        start_x = event.get('startPosXM')
        end_x = event.get('endPosXM')
        start_y = event.get('startPosYM')
        end_y = event.get('endPosYM')
        
        time_ms = event.get('startTimeMs', 0) or event.get('timeMs', 0) or event.get('timestampMs', 0)
        minute = time_ms / 1000 / 60 if time_ms else 0
        
        if not time_ms:
            continue
        
        domination_value = 0
        control_value = 0
        domination_type = None
        control_type = None
        
        # Determine half
        part_id = event.get('partId')
        part_name = event.get('partName', '').upper()
        
        if part_id == 1 or part_name == 'FIRST_HALF' or part_name == 'FIRST HALF':
            target_domination_events = first_half_domination_events
            target_control_events = first_half_control_events
            target_goals = first_half_goals
            target_subs = first_half_subs
            target_cards = first_half_cards
        elif part_id == 2 or part_name == 'SECOND_HALF' or part_name == 'SECOND HALF':
            target_domination_events = second_half_domination_events
            target_control_events = second_half_control_events
            target_goals = second_half_goals
            target_subs = second_half_subs
            target_cards = second_half_cards
        else:
            continue
        
        # Check for goals
        if base_type_id == BASE_TYPE['SHOT'] and result_id == RESULT['SUCCESSFUL']:
            target_goals.append({
                'team': team,
                'minute': minute,
                'player': event.get('playerName', 'Unknown')
            })
            domination_value = DOMINATION_WEIGHTS['GOAL'] + (event.get('metrics', {}).get('xG', 0.0) * DOMINATION_WEIGHTS['XG_MULTIPLIER'])
            domination_type = 'GOAL'
        
        # Check for own goals
        elif sub_type_id == SUB_TYPE['OWN_GOAL']:
            opposing_team = away_team if team == home_team else home_team
            target_goals.append({
                'team': opposing_team,
                'minute': minute,
                'player': f"OG: {event.get('playerName', 'Unknown')}"
            })
            target_domination_events.append({
                'team': opposing_team,
                'minute': minute,
                'value': DOMINATION_WEIGHTS['GOAL'],
                'type': 'OWN_GOAL'
            })
            continue
        
        # Other shot types
        elif base_type_id == BASE_TYPE['SHOT']:
            xg_value = event.get('metrics', {}).get('xG', 0.0) * DOMINATION_WEIGHTS['XG_MULTIPLIER']
            if shot_type_id == SHOT_TYPE['ON_TARGET']:
                domination_value = DOMINATION_WEIGHTS['SHOT_ON_TARGET'] + xg_value
                domination_type = 'SHOT_ON_TARGET'
            elif shot_type_id == SHOT_TYPE['POST']:
                domination_value = DOMINATION_WEIGHTS['SHOT_POST'] + xg_value
                domination_type = 'SHOT_POST'
            elif shot_type_id == SHOT_TYPE['BLOCKED']:
                domination_value = DOMINATION_WEIGHTS['SHOT_BLOCKED'] + xg_value
                domination_type = 'SHOT_BLOCKED'
            elif shot_type_id == SHOT_TYPE['WIDE']:
                domination_value = DOMINATION_WEIGHTS['SHOT_WIDE'] + xg_value
                domination_type = 'SHOT_WIDE'
        
        # Substitutions
        elif base_type_id == BASE_TYPE['SUBSTITUTE']:
            if sub_type_id == SUB_TYPE['SUBBED_IN']:
                player_out = 'Unknown'
                for other_event in events:
                    if (other_event.get('baseTypeId') == BASE_TYPE['SUBSTITUTE'] and
                        other_event.get('subTypeId') == SUB_TYPE['SUBBED_OUT'] and
                        abs((other_event.get('startTimeMs', 0) or 0) - time_ms) < 1000 and
                        match_event_team(other_event.get('teamName') or other_event.get('team')) == team):
                        player_out = other_event.get('playerName', 'Unknown')
                        break
                
                target_subs.append({
                    'team': team,
                    'minute': minute,
                    'player_in': event.get('playerName', 'Unknown'),
                    'player_out': player_out
                })
        
        # Cards
        if base_type_id == 15:
            if sub_type_id in (1501, 1502):
                target_cards.append({
                    'team': team,
                    'minute': minute,
                    'player': event.get('playerName', 'Unknown'),
                    'type': 'RED'
                })
        
        # Passes
        if base_type_id == BASE_TYPE['PASS']:
            if result_id == RESULT['SUCCESSFUL']:
                if sub_type_id == SUB_TYPE.get('KEY_PASS'):
                    control_value += CONTROL_WEIGHTS['PASS_KEY']
                    control_type = 'PASS_KEY'
                
                if start_x is not None and end_x is not None:
                    in_final_third = (start_x >= 17.5) and (end_x > 17.5)
                    to_final_third = (start_x < 17.5) and (end_x > 17.5)
                    
                    if to_final_third:
                        control_value += CONTROL_WEIGHTS['PASS_TO_FINAL_THIRD']
                        control_type = 'PASS_TO_FINAL_THIRD'
                    elif in_final_third:
                        control_value += CONTROL_WEIGHTS['PASS_IN_FINAL_THIRD']
                        control_type = 'PASS_IN_FINAL_THIRD'
            
            if result_id == RESULT['SUCCESSFUL'] and start_x is not None and end_x is not None:
                in_box = (start_x >= 36) and (end_x > 36) and (end_y is not None and abs(end_y) < 20.15)
                to_box = (start_x < 36) and (end_x > 36) and (end_y is not None and abs(end_y) < 20.15)
                
                if to_box:
                    domination_value = DOMINATION_WEIGHTS['PASS_TO_BOX']
                    domination_type = 'PASS_TO_BOX'
                elif in_box:
                    domination_value = DOMINATION_WEIGHTS['PASS_IN_BOX']
                    domination_type = 'PASS_IN_BOX'
        
        # Interceptions
        elif base_type_id == BASE_TYPE['INTERCEPTION']:
            if sub_type_id == SUB_TYPE.get('COUNTER_INTERCEPTION'):
                control_value = CONTROL_WEIGHTS['COUNTER_INTERCEPTION']
                control_type = 'COUNTER_INTERCEPTION'
            else:
                control_value = CONTROL_WEIGHTS['INTERCEPTION']
                control_type = 'INTERCEPTION'
            
            if start_x is not None and start_x > 17.5:
                domination_value = DOMINATION_WEIGHTS['INTERCEPTION_FINAL_THIRD']
                domination_type = 'INTERCEPTION_FINAL_THIRD'
        
        # Dribbles
        elif base_type_id == BASE_TYPE['DRIBBLE'] and result_id == RESULT['SUCCESSFUL']:
            to_box = (start_x < 36) and (end_x > 36) and (end_y is not None and abs(end_y) < 20.15)
            
            if to_box:
                domination_value = DOMINATION_WEIGHTS['DRIBBLE_TO_BOX']
                domination_type = 'DRIBBLE_TO_BOX'
            else:
                control_value = CONTROL_WEIGHTS['DRIBBLE_SUCCESSFUL']
                control_type = 'DRIBBLE_SUCCESSFUL'
        
        # Ball recoveries
        elif base_type_id == BASE_TYPE.get('BALL_RECOVERY'):
            if sub_type_id == SUB_TYPE.get('COUNTER_INTERCEPTION'):
                control_value = CONTROL_WEIGHTS['COUNTER_INTERCEPTION']
                control_type = 'COUNTER_INTERCEPTION'
            else:
                control_value = CONTROL_WEIGHTS.get('BALL_RECOVERY', 2)
                control_type = 'BALL_RECOVERY'
        
        # Add to events lists
        if domination_value > 0:
            target_domination_events.append({
                'team': team,
                'minute': minute,
                'value': domination_value,
                'type': domination_type
            })
        
        if control_value > 0:
            target_control_events.append({
                'team': team,
                'minute': minute,
                'value': control_value,
                'type': control_type
            })
    
    # Function to calculate metrics for a specific half
    def calculate_half_metrics(domination_events, control_events, start_minute, end_minute):
        if not domination_events and not control_events:
            return [], [], [], [], [], [], []
        
        minutes = np.arange(start_minute, end_minute + 0.5, 0.5)
        home_domination = []
        away_domination = []
        net_domination = []
        home_control = []
        away_control = []
        net_control = []
        window_size = 5
        
        for current_minute in minutes:
            window_start = max(start_minute, current_minute - window_size)
            window_end = current_minute
            
            home_dom_sum = sum(e['value'] for e in domination_events
                          if e['team'] == home_team and window_start <= e['minute'] <= window_end)
            away_dom_sum = sum(e['value'] for e in domination_events
                          if e['team'] == away_team and window_start <= e['minute'] <= window_end)
            
            home_domination.append(home_dom_sum)
            away_domination.append(away_dom_sum)
            net_domination.append(home_dom_sum - away_dom_sum)
            
            home_ctrl_sum = sum(e['value'] for e in control_events
                          if e['team'] == home_team and window_start <= e['minute'] <= window_end)
            away_ctrl_sum = sum(e['value'] for e in control_events
                          if e['team'] == away_team and window_start <= e['minute'] <= window_end)
            
            home_control.append(home_ctrl_sum)
            away_control.append(away_ctrl_sum)
            net_control.append(home_ctrl_sum - away_ctrl_sum)
        
        total_home_control = sum(e['value'] for e in control_events if e['team'] == home_team)
        total_away_control = sum(e['value'] for e in control_events if e['team'] == away_team)
        
        return minutes, net_domination, net_control, home_domination, away_domination, home_control, away_control
    
    # Calculate metrics for each half
    first_half_start = min([e['minute'] for e in first_half_domination_events + first_half_control_events]) if (first_half_domination_events or first_half_control_events) else 0
    first_half_end = max([e['minute'] for e in first_half_domination_events + first_half_control_events]) if (first_half_domination_events or first_half_control_events) else 45
    
    second_half_start = min([e['minute'] for e in second_half_domination_events + second_half_control_events]) if (second_half_domination_events or second_half_control_events) else 45
    second_half_end = max([e['minute'] for e in second_half_domination_events + second_half_control_events]) if (second_half_domination_events or second_half_control_events) else 90
    
    first_half_minutes, first_half_net_dom, first_half_net_ctrl, first_half_home_dom, first_half_away_dom, first_half_home_ctrl, first_half_away_ctrl = calculate_half_metrics(
        first_half_domination_events, first_half_control_events, first_half_start, first_half_end
    )
    
    second_half_minutes, second_half_net_dom, second_half_net_ctrl, second_half_home_dom, second_half_away_dom, second_half_home_ctrl, second_half_away_ctrl = calculate_half_metrics(
        second_half_domination_events, second_half_control_events, second_half_start, second_half_end
    )
    
    # Calculate durations
    first_half_duration = first_half_end - first_half_start if (first_half_domination_events or first_half_control_events) else 45
    second_half_duration = second_half_end - second_half_start if (second_half_domination_events or second_half_control_events) else 45
    
    total_duration = first_half_duration + second_half_duration
    first_half_ratio = first_half_duration / total_duration if total_duration > 0 else 0.5
    second_half_ratio = second_half_duration / total_duration if total_duration > 0 else 0.5
    
    # Create visualization
    fig = plt.figure(figsize=(20, 9), constrained_layout=True)
    gs = gridspec.GridSpec(2, 2, width_ratios=[first_half_ratio, second_half_ratio],
                          height_ratios=[5, 1], hspace=0.25, figure=fig)
    ax1 = fig.add_subplot(gs[0, 0])
    ax2 = fig.add_subplot(gs[0, 1])
    ax_bar = fig.add_subplot(gs[1, :])
    
    home_plot_color = home_color
    away_plot_color = away_color
    
    # Plot function
    def plot_half(ax, minutes, home_domination, away_domination, net_control, home_control, away_control,
                  goals, subs, cards, half_name, home_color, away_color, home_team_name, away_team_name):
        ax.set_facecolor('#f5f5f5')
        
        if len(minutes) == 0:
            ax.text(0.5, 0.5, f'No data for {half_name}', ha='center', va='center', transform=ax.transAxes)
            return
        
        ax.axhline(y=0, color='#95A5A6', linestyle='-', linewidth=1)
        
        control_minutes = minutes
        control_values = net_control
        
        ax.plot(control_minutes, control_values, color='#2E4053', linewidth=1.5, zorder=4)
        
        for i in range(len(control_minutes)-1):
            if control_values[i] > 0 or control_values[i+1] > 0:
                ax.fill_between([control_minutes[i], control_minutes[i+1]], 0,
                               [control_values[i], control_values[i+1]],
                               color=home_color, alpha=0.6, zorder=2)
            elif control_values[i] < 0 or control_values[i+1] < 0:
                ax.fill_between([control_minutes[i], control_minutes[i+1]], 0,
                               [control_values[i], control_values[i+1]],
                               color=away_color, alpha=0.6, zorder=2)
        
        if len(minutes) > 1 and len(home_domination) > 1 and len(away_domination) > 1:
            domination_indices = list(range(0, len(minutes), 1))
            if domination_indices[-1] != len(minutes) - 1:
                domination_indices.append(len(minutes) - 1)
            
            smooth_minutes = np.array([minutes[i] for i in domination_indices])
            smooth_home_domination = [home_domination[i] for i in domination_indices]
            smooth_away_domination = [-away_domination[i] for i in domination_indices]
        else:
            smooth_minutes = minutes
            smooth_home_domination = home_domination
            smooth_away_domination = [-away_domination[i] for i in range(len(away_domination))]
        
        ax.plot(smooth_minutes, smooth_home_domination, color='red', linewidth=2,
                linestyle='--', zorder=6, label=f'{home_team_name} Danger', alpha=0.9, dashes=(5, 3))
        ax.plot(smooth_minutes, smooth_away_domination, color='black', linewidth=2,
                linestyle='--', zorder=6, label=f'{away_team_name} Danger', alpha=0.9, dashes=(5, 3))
        
        y_limit = 80
        ax.set_ylim(-y_limit, y_limit)
        
        # Add goal markers
        home_goals_half = [g for g in goals if g['team'] == home_team_name]
        away_goals_half = [g for g in goals if g['team'] == away_team_name]
        
        for goal in home_goals_half:
            ax.axvline(x=goal['minute'], ymin=0.5, ymax=1, color=home_color,
                      linestyle='--', linewidth=1.5, alpha=0.7)
            if ball_icon is not None:
                ax.imshow(ball_icon, extent=(goal['minute'] - 0.75, goal['minute'] + 0.75,
                         y_limit * 0.8, y_limit * 0.9), aspect="auto", zorder=10)
            else:
                ax.scatter(goal['minute'], y_limit * 0.85, s=300, marker='o',
                          color='white', edgecolor=home_color, linewidth=2, zorder=10)
                ax.text(goal['minute'], y_limit * 0.85, 'G', fontsize=12, ha='center', va='center',
                       fontweight='bold', color=home_color)
        
        for goal in away_goals_half:
            ax.axvline(x=goal['minute'], ymin=0, ymax=0.5, color=away_color,
                      linestyle='--', linewidth=1.5, alpha=0.7)
            if ball_icon is not None:
                ax.imshow(ball_icon, extent=(goal['minute'] - 0.75, goal['minute'] + 0.75,
                         -y_limit * 0.9, -y_limit * 0.8), aspect="auto", zorder=10)
            else:
                ax.scatter(goal['minute'], -y_limit * 0.85, s=300, marker='o',
                          color='white', edgecolor=away_color, linewidth=2, zorder=10)
                ax.text(goal['minute'], -y_limit * 0.85, 'G', fontsize=12, ha='center', va='center',
                       fontweight='bold', color=away_color)
        
        # Add substitution markers
        for sub in subs:
            sub_minute = sub['minute']
            if half_name == 'First Half' and abs(sub_minute - minutes[-1]) < 1:
                continue
            elif half_name == 'Second Half' and abs(sub_minute - minutes[0]) < 1:
                sub_minute = minutes[0]
            
            if sub['team'] == home_team_name:
                ax.axvline(x=sub_minute, ymin=0.5, ymax=1, color='#7F8C8D',
                          linestyle='--', linewidth=1, alpha=0.5)
                y_pos_bottom = y_limit * 0.65
                y_pos_top = y_limit * 0.75
            else:
                ax.axvline(x=sub_minute, ymin=0, ymax=0.5, color='#7F8C8D',
                          linestyle='--', linewidth=1, alpha=0.5)
                y_pos_bottom = -y_limit * 0.75
                y_pos_top = -y_limit * 0.65
            
            if sub_icon is not None:
                ax.imshow(sub_icon, extent=(sub_minute - 0.75, sub_minute + 0.75,
                         y_pos_bottom, y_pos_top), aspect="auto", zorder=9)
            else:
                ax.scatter(sub_minute, (y_pos_bottom + y_pos_top)/2, s=150, marker='o',
                          color='white', edgecolor='#7F8C8D', linewidth=2, zorder=9)
                ax.text(sub_minute, (y_pos_bottom + y_pos_top)/2, 'S', fontsize=10, ha='center', va='center',
                       color='#7F8C8D', fontweight='bold')
        
        # Add red card markers
        for card in cards:
            card_minute = card['minute']
            if card['team'] == home_team_name:
                ax.axvline(x=card_minute, ymin=0.5, ymax=1, color='red', linestyle='--', linewidth=1.5, alpha=0.8)
                y_bottom = y_limit * 0.70
                y_top = y_limit * 0.80
                if redcard_icon is not None:
                    ax.imshow(redcard_icon, extent=(card_minute - 0.5, card_minute + 0.5, y_bottom, y_top),
                              aspect='auto', zorder=11)
                else:
                    ax.scatter(card_minute, y_limit * 0.75, s=220, marker='s', color='red', zorder=11)
                    ax.text(card_minute, y_limit * 0.75, 'RC', fontsize=9, ha='center', va='center', color='white', fontweight='bold')
            else:
                ax.axvline(x=card_minute, ymin=0, ymax=0.5, color='red', linestyle='--', linewidth=1.5, alpha=0.8)
                y_bottom = -y_limit * 0.80
                y_top = -y_limit * 0.70
                if redcard_icon is not None:
                    ax.imshow(redcard_icon, extent=(card_minute - 0.5, card_minute + 0.5, y_bottom, y_top),
                              aspect='auto', zorder=11)
                else:
                    ax.scatter(card_minute, -y_limit * 0.75, s=220, marker='s', color='red', zorder=11)
                    ax.text(card_minute, -y_limit * 0.75, 'RC', fontsize=9, ha='center', va='center', color='white', fontweight='bold')
        
        ax.grid(True, alpha=0.2, color='white', linewidth=1)
        ax.set_axisbelow(True)
        
        x_padding = 1
        ax.set_xlim(minutes[0] - x_padding, minutes[-1] + x_padding)
        
        step = 15 if (minutes[-1] - minutes[0]) >= 30 else max(1, int((minutes[-1] - minutes[0]) // 5))
        ticks = np.arange(minutes[0], minutes[-1] + 1, step)
        
        if half_name == 'Second Half' and len(minutes) > 0:
            offset = 45 - minutes[0]
            ax.set_xticks(ticks)
            ax.set_xticklabels([f"{int(t + offset)}'" for t in ticks])
        else:
            ax.set_xticks(ticks)
            ax.set_xticklabels([f"{int(t)}'" for t in ticks])
        
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_visible(False)
        ax.set_yticks([])
        
        ax.set_title(half_name, fontsize=14, fontweight='bold', pad=10)
        
        if half_name == 'First Half':
            ax.text(0.02, 0.95, 'Control:', transform=ax.transAxes, fontsize=9, ha='left', va='center')
            
            home_rect = Rectangle((0.12, 0.945), 0.02, 0.012,
                                 facecolor=home_color, alpha=0.6,
                                 transform=ax.transAxes)
            ax.add_patch(home_rect)
            
            away_rect = Rectangle((0.14, 0.945), 0.02, 0.012,
                                facecolor=away_color, alpha=0.6,
                                transform=ax.transAxes)
            ax.add_patch(away_rect)
            
            ax.text(0.02, 0.91, 'Danger:', transform=ax.transAxes, fontsize=9, ha='left', va='center')
            
            ax.plot([0.12, 0.14], [0.91, 0.91],
                   color='red', linewidth=2,
                   linestyle='--', alpha=0.9, transform=ax.transAxes, dashes=(3, 1.5))
            
            ax.plot([0.14, 0.16], [0.91, 0.91],
                   color='black', linewidth=2,
                   linestyle='--', alpha=0.9, transform=ax.transAxes, dashes=(3, 1.5))
    
    # Plot both halves
    plot_half(ax1, first_half_minutes, first_half_home_dom, first_half_away_dom,
              first_half_net_ctrl, first_half_home_ctrl, first_half_away_ctrl,
              first_half_goals, first_half_subs, first_half_cards, 'First Half', 
              home_plot_color, away_plot_color, home_team, away_team)
    
    plot_half(ax2, second_half_minutes, second_half_home_dom, second_half_away_dom,
              second_half_net_ctrl, second_half_home_ctrl, second_half_away_ctrl,
              second_half_goals, second_half_subs, second_half_cards, 'Second Half', 
              home_plot_color, away_plot_color, home_team, away_team)
    
    # Calculate overall percentages
    all_control_events = first_half_control_events + second_half_control_events
    all_domination_events = first_half_domination_events + second_half_domination_events
    all_cards = first_half_cards + second_half_cards
    
    match_start = first_half_start
    match_end = second_half_end
    match_total_duration = max(1.0, (match_end - match_start))
    
    def compute_pct_by_team(events_list, start_time, end_time, teamA, teamB):
        home_sum = sum(e['value'] for e in events_list if e['team'] == teamA and start_time <= e['minute'] < end_time)
        away_sum = sum(e['value'] for e in events_list if e['team'] == teamB and start_time <= e['minute'] < end_time)
        total = home_sum + away_sum
        if total <= 0:
            return 50.0, 50.0
        return (home_sum / total * 100.0), (away_sum / total * 100.0)
    
    # Handle red card split if present
    if len(all_cards) > 0:
        card_minute = min(c['minute'] for c in all_cards)
        card_minute = max(match_start, min(card_minute, match_end - 1e-6))

        # Do not split if card occurs within 5 minutes of start or 5 minutes of end
        too_close_to_edges = ((card_minute - match_start) < 5) or ((match_end - card_minute) < 5)

        if too_close_to_edges:
            # Standard bars (no split)
            total_home_control_points = sum(e['value'] for e in all_control_events if e['team'] == home_team)
            total_away_control_points = sum(e['value'] for e in all_control_events if e['team'] == away_team)
            total_control_points = total_home_control_points + total_away_control_points
            if total_control_points > 0:
                home_control_pct = (total_home_control_points / total_control_points) * 100
                away_control_pct = (total_away_control_points / total_control_points) * 100
            else:
                home_control_pct = away_control_pct = 50

            total_home_danger_points = sum(e['value'] for e in all_domination_events if e['team'] == home_team)
            total_away_danger_points = sum(e['value'] for e in all_domination_events if e['team'] == away_team)
            total_danger_points = total_home_danger_points + total_away_danger_points
            if total_danger_points > 0:
                home_danger_pct = (total_home_danger_points / total_danger_points) * 100
                away_danger_pct = (total_away_danger_points / total_danger_points) * 100
            else:
                home_danger_pct = away_danger_pct = 50

            ax_bar.barh([1], [home_control_pct], color=home_plot_color, alpha=0.8, height=0.85)
            ax_bar.barh([1], [away_control_pct], left=[home_control_pct], color=away_plot_color, alpha=0.8, height=0.85)
            ax_bar.barh([0], [home_danger_pct], color=home_plot_color, alpha=0.8, height=0.85)
            ax_bar.barh([0], [away_danger_pct], left=[home_danger_pct], color=away_plot_color, alpha=0.8, height=0.85)
            ax_bar.set_xlim(0, 100)
            ax_bar.set_ylim(-0.65, 1.65)
            ax_bar.set_yticks([0, 1])
            ax_bar.set_yticklabels(['Danger', 'Control'], fontsize=12, fontweight='bold')
            ax_bar.set_xticks([])
            ax_bar.set_xlabel('')
            ax_bar.text(home_control_pct/2, 1, f'{home_control_pct:.0f}%',
                        ha='center', va='center', color='white', fontweight='bold', fontsize=13)
            ax_bar.text(home_control_pct + away_control_pct/2, 1, f'{away_control_pct:.0f}%',
                        ha='center', va='center', color='white', fontweight='bold', fontsize=13)
            ax_bar.text(home_danger_pct/2, 0, f'{home_danger_pct:.0f}%',
                        ha='center', va='center', color='white', fontweight='bold', fontsize=13)
            ax_bar.text(home_danger_pct + away_danger_pct/2, 0, f'{away_danger_pct:.0f}%',
                        ha='center', va='center', color='white', fontweight='bold', fontsize=13)
            ax_bar.spines['top'].set_visible(False)
            ax_bar.spines['right'].set_visible(False)
            ax_bar.spines['bottom'].set_visible(False)
        else:
            # Compute bar split based on plotted spans of first/second half
            first_half_plotted_duration = (first_half_minutes[-1] - first_half_minutes[0]) if (hasattr(first_half_minutes, 'size') and first_half_minutes.size > 0) else 0
            second_half_plotted_duration = (second_half_minutes[-1] - second_half_minutes[0]) if (hasattr(second_half_minutes, 'size') and second_half_minutes.size > 0) else 0
            total_plotted_span_actual = first_half_plotted_duration + second_half_plotted_duration

            if total_plotted_span_actual <= 0:
                bar_split_point_pct = 50.0
            else:
                if (card_minute <= first_half_end) and (hasattr(first_half_minutes, 'size') and first_half_minutes.size > 0):
                    time_before_card_on_plot = card_minute - first_half_minutes[0]
                elif hasattr(second_half_minutes, 'size') and second_half_minutes.size > 0:
                    time_before_card_on_plot = first_half_plotted_duration + (card_minute - second_half_minutes[0])
                else:
                    time_before_card_on_plot = 0

                bar_split_point_pct = (time_before_card_on_plot / total_plotted_span_actual) * 100.0
                bar_split_point_pct = float(np.clip(bar_split_point_pct, 0.0, 100.0))

            # Percentages pre/post card
            pre_home_ctrl_pct, pre_away_ctrl_pct = compute_pct_by_team(all_control_events, match_start, card_minute, home_team, away_team)
            post_home_ctrl_pct, post_away_ctrl_pct = compute_pct_by_team(all_control_events, card_minute, match_end, home_team, away_team)

            pre_home_danger_pct, pre_away_danger_pct = compute_pct_by_team(all_domination_events, match_start, card_minute, home_team, away_team)
            post_home_danger_pct, post_away_danger_pct = compute_pct_by_team(all_domination_events, card_minute, match_end, home_team, away_team)

            # Absolute widths
            pre_seg_width = bar_split_point_pct
            post_seg_width = 100.0 - bar_split_point_pct

            home_pre_width = pre_home_ctrl_pct / 100.0 * pre_seg_width
            away_pre_width = pre_seg_width - home_pre_width

            home_post_width = post_home_ctrl_pct / 100.0 * post_seg_width
            away_post_width = post_seg_width - home_post_width

            home_pre_danger_width = pre_home_danger_pct / 100.0 * pre_seg_width
            away_pre_danger_width = pre_seg_width - home_pre_danger_width

            home_post_danger_width = post_home_danger_pct / 100.0 * post_seg_width
            away_post_danger_width = post_seg_width - home_post_danger_width

            ax_bar.clear()
            ax_bar.set_xlim(0, 100)
            ax_bar.set_ylim(-0.65, 1.65)
            ax_bar.set_yticks([0, 1])
            ax_bar.set_yticklabels(['Danger', 'Control'], fontsize=12, fontweight='bold')
            ax_bar.set_xticks([])

            # Control row
            ax_bar.barh([1], [home_pre_width], left=[0], color=home_plot_color, alpha=0.8, height=0.85)
            ax_bar.barh([1], [away_pre_width], left=[home_pre_width], color=away_plot_color, alpha=0.8, height=0.85)
            ax_bar.barh([1], [home_post_width], left=[pre_seg_width], color=home_plot_color, alpha=0.8, height=0.85)
            ax_bar.barh([1], [away_post_width], left=[pre_seg_width + home_post_width], color=away_plot_color, alpha=0.8, height=0.85)

            # Danger row
            ax_bar.barh([0], [home_pre_danger_width], left=[0], color=home_plot_color, alpha=0.8, height=0.85)
            ax_bar.barh([0], [away_pre_danger_width], left=[home_pre_danger_width], color=away_plot_color, alpha=0.8, height=0.85)
            ax_bar.barh([0], [home_post_danger_width], left=[pre_seg_width], color=home_plot_color, alpha=0.8, height=0.85)
            ax_bar.barh([0], [away_post_danger_width], left=[pre_seg_width + home_post_danger_width], color=away_plot_color, alpha=0.8, height=0.85)

            # Red card marker
            ax_bar.axvline(x=pre_seg_width, color='red', linestyle=':', linewidth=1.2, zorder=5)

            def maybe_text(x_start, width, y, txt):
                if width >= 3:
                    ax_bar.text(x_start + width / 2.0, y, txt, ha='center', va='center', color='white', fontweight='bold', fontsize=11)

            maybe_text(0, home_pre_width, 1, f'{pre_home_ctrl_pct:.0f}%')
            maybe_text(home_pre_width, away_pre_width, 1, f'{pre_away_ctrl_pct:.0f}%')
            maybe_text(pre_seg_width, home_post_width, 1, f'{post_home_ctrl_pct:.0f}%')
            maybe_text(pre_seg_width + home_post_width, away_post_width, 1, f'{post_away_ctrl_pct:.0f}%')

            maybe_text(0, home_pre_danger_width, 0, f'{pre_home_danger_pct:.0f}%')
            maybe_text(home_pre_danger_width, away_pre_danger_width, 0, f'{pre_away_danger_pct:.0f}%')
            maybe_text(pre_seg_width, home_post_danger_width, 0, f'{post_home_danger_pct:.0f}%')
            maybe_text(pre_seg_width + home_post_danger_width, away_post_danger_width, 0, f'{post_away_danger_pct:.0f}%')

            ax_bar.spines['top'].set_visible(False)
            ax_bar.spines['right'].set_visible(False)
            ax_bar.spines['bottom'].set_visible(False)
    
    else:
        # No red card - standard bars
        total_home_control_points = sum(e['value'] for e in all_control_events if e['team'] == home_team)
        total_away_control_points = sum(e['value'] for e in all_control_events if e['team'] == away_team)
        total_control_points = total_home_control_points + total_away_control_points
        
        if total_control_points > 0:
            home_control_pct = (total_home_control_points / total_control_points) * 100
            away_control_pct = (total_away_control_points / total_control_points) * 100
        else:
            home_control_pct = away_control_pct = 50
        
        total_home_danger_points = sum(e['value'] for e in all_domination_events if e['team'] == home_team)
        total_away_danger_points = sum(e['value'] for e in all_domination_events if e['team'] == away_team)
        total_danger_points = total_home_danger_points + total_away_danger_points
        
        if total_danger_points > 0:
            home_danger_pct = (total_home_danger_points / total_danger_points) * 100
            away_danger_pct = (total_away_danger_points / total_danger_points) * 100
        else:
            home_danger_pct = away_danger_pct = 50
        
        ax_bar.barh([1], [home_control_pct], color=home_plot_color, alpha=0.8, height=0.85)
        ax_bar.barh([1], [away_control_pct], left=[home_control_pct], color=away_plot_color, alpha=0.8, height=0.85)
        
        ax_bar.barh([0], [home_danger_pct], color=home_plot_color, alpha=0.8, height=0.85)
        ax_bar.barh([0], [away_danger_pct], left=[home_danger_pct], color=away_plot_color, alpha=0.8, height=0.85)
        
        ax_bar.set_xlim(0, 100)
        ax_bar.set_ylim(-0.65, 1.65)
        ax_bar.set_yticks([0, 1])
        ax_bar.set_yticklabels(['Danger', 'Control'], fontsize=12, fontweight='bold')
        ax_bar.set_xticks([])
        ax_bar.set_xlabel('')
        
        ax_bar.text(home_control_pct/2, 1, f'{home_control_pct:.0f}%',
                   ha='center', va='center', color='white', fontweight='bold', fontsize=13)
        ax_bar.text(home_control_pct + away_control_pct/2, 1, f'{away_control_pct:.0f}%',
                   ha='center', va='center', color='white', fontweight='bold', fontsize=13)
        
        ax_bar.text(home_danger_pct/2, 0, f'{home_danger_pct:.0f}%',
                   ha='center', va='center', color='white', fontweight='bold', fontsize=13)
        ax_bar.text(home_danger_pct + away_danger_pct/2, 0, f'{away_danger_pct:.0f}%',
                   ha='center', va='center', color='white', fontweight='bold', fontsize=13)
        
        ax_bar.spines['top'].set_visible(False)
        ax_bar.spines['right'].set_visible(False)
        ax_bar.spines['bottom'].set_visible(False)
    
    # Add score
    total_home_goals = len([g for g in first_half_goals + second_half_goals if g['team'] == home_team])
    total_away_goals = len([g for g in first_half_goals + second_half_goals if g['team'] == away_team])
    
    fig.suptitle(f'{home_team} {total_home_goals} - {total_away_goals} {away_team}',
                 fontsize=18, fontweight='bold', y=1.02)
    
    return fig, {
        'first_half': {
            'minutes': first_half_minutes,
            'net_domination': first_half_net_dom,
            'net_control': first_half_net_ctrl,
            'domination_events': first_half_domination_events,
            'control_events': first_half_control_events,
            'goals': first_half_goals,
            'substitutions': first_half_subs,
            'cards': first_half_cards
        },
        'second_half': {
            'minutes': second_half_minutes,
            'net_domination': second_half_net_dom,
            'net_control': second_half_net_ctrl,
            'domination_events': second_half_domination_events,
            'control_events': second_half_control_events,
            'goals': second_half_goals,
            'substitutions': second_half_subs,
            'cards': second_half_cards
        }
    }

# Main app
if events_data is not None:
    with st.spinner("Analyzing player performance..."):
        # Get teams and events for player analysis
        metadata = events_data.get('metaData', {}) if isinstance(events_data, dict) else {}
        home_team = metadata.get('homeTeamName') or metadata.get('homeTeam') or metadata.get('home') or 'Home'
        away_team = metadata.get('awayTeamName') or metadata.get('awayTeam') or metadata.get('away') or 'Away'
        events = events_data.get('data', []) if isinstance(events_data, dict) else []

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
        all_shots = find_shot_events(events)
        
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