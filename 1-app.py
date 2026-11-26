import streamlit as st
import pandas as pd
import pymysql

st.set_page_config(page_title="SMAT 2026/27 Dashboard", page_icon="🏏", layout="wide")

# ---------- data ----------
@st.cache_resource
def get_conn():
    s = st.secrets["tidb"]
    return pymysql.connect(
        host=s["host"], port=int(s["port"]), user=s["user"],
        password=s["password"], database=s["database"],
        ssl={}, charset="utf8mb4", autocommit=True,
    )

@st.cache_data(ttl=600)
def q(sql, params=None):
    conn = get_conn()
    conn.ping()
    with conn.cursor() as cur:
        cur.execute(sql, params or ())
        cols = [d[0] for d in cur.description]
        df = pd.DataFrame(cur.fetchall(), columns=cols)
    for c in df.columns:
        if df[c].dtype == object:
            try:
                df[c] = pd.to_numeric(df[c])
            except (ValueError, TypeError):
                pass
    return df

def overs(balls):
    return f"{int(balls)//6}.{int(balls)%6}"

def result_text(r):
    if r["winner"] is None or pd.isna(r["winner"]):
        return "No result"
    if r["result_by"] == "wickets":
        return f"{r['winner']} won by {int(r['result_margin'])} wickets"
    if r["result_by"] == "runs":
        return f"{r['winner']} won by {int(r['result_margin'])} runs"
    return f"{r['winner']} won"

# ---------- header ----------
st.title("🏏 Syed Mushtaq Ali Trophy 2026/27")
st.caption("Live stats from a MySQL-compatible TiDB Cloud database, refreshed daily from Cricsheet ball-by-ball data.")

tab_over, tab_bat, tab_bowl, tab_matches, tab_points = st.tabs(
    ["Overview", "Batting", "Bowling", "Matches", "Points Table"])

# ---------- overview ----------
with tab_over:
    m = q("SELECT COUNT(*) AS matches FROM matches")
    p = q("SELECT COUNT(*) AS players FROM players")
    t = q("SELECT COUNT(*) AS teams FROM teams")
    runs = q("SELECT SUM(runs) AS r FROM batting")
    wk = q("SELECT SUM(wickets) AS w FROM bowling")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Matches", int(m["matches"][0]))
    c2.metric("Teams", int(t["teams"][0]))
    c3.metric("Players", int(p["players"][0]))
    c4.metric("Runs scored", int(runs["r"][0]))
    c5.metric("Wickets", int(wk["w"][0]))

    recent = q("""
        SELECT m.match_date AS Date, t1.name AS Team1, t2.name AS Team2,
               w.name AS winner, m.result_by, m.result_margin, m.venue AS Venue
        FROM matches m
        JOIN teams t1 ON t1.team_id = m.team1_id
        JOIN teams t2 ON t2.team_id = m.team2_id
        LEFT JOIN teams w ON w.team_id = m.winner_id
        ORDER BY m.match_date DESC, m.match_id DESC LIMIT 12""")
    recent["Result"] = recent.apply(result_text, axis=1)
    st.subheader("Latest results")
    st.dataframe(recent[["Date", "Team1", "Team2", "Result", "Venue"]],
                 hide_index=True, width='stretch')

    left, right = st.columns(2)
    top_bat = q("SELECT name, runs FROM career_batting ORDER BY runs DESC LIMIT 10")
    top_bowl = q("SELECT name, wickets FROM career_bowling ORDER BY wickets DESC, economy LIMIT 10")
    with left:
        st.subheader("Most runs")
        st.bar_chart(top_bat.set_index("name"))
    with right:
        st.subheader("Most wickets")
        st.bar_chart(top_bowl.set_index("name"))

# ---------- batting ----------
with tab_bat:
    bat = q("""
        SELECT cb.name AS Player, t.name AS Team, cb.innings AS Inns, cb.not_outs AS NO,
               cb.runs AS Runs, cb.high_score AS HS, cb.balls AS Balls,
               cb.strike_rate AS SR, cb.fours AS `4s`, cb.sixes AS `6s`,
               cb.player_id
        FROM career_batting cb
        LEFT JOIN (SELECT DISTINCT player_id, team_id FROM match_players) mp ON mp.player_id = cb.player_id
        LEFT JOIN teams t ON t.team_id = mp.team_id
        ORDER BY cb.runs DESC""")
    f1, f2 = st.columns([2, 1])
    teams = ["All teams"] + sorted(bat["Team"].dropna().unique().tolist())
    team_pick = f1.selectbox("Team", teams, key="bat_team")
    min_runs = f2.slider("Minimum runs", 0, int(bat["Runs"].max()), 0, 10)
    view = bat[bat["Runs"] >= min_runs]
    if team_pick != "All teams":
        view = view[view["Team"] == team_pick]
    st.dataframe(view.drop(columns=["player_id"]), hide_index=True, width='stretch', height=420)

    st.subheader("Player innings by innings")
    pick = st.selectbox("Player", view["Player"].tolist(), key="bat_player")
    if pick:
        pid = bat.loc[bat["Player"] == pick, "player_id"].iloc[0]
        inn = q("""
            SELECT m.match_date AS Date, opp.name AS Against, b.runs AS Runs, b.balls AS Balls,
                   b.fours AS `4s`, b.sixes AS `6s`,
                   ROUND(100.0*b.runs/NULLIF(b.balls,0),1) AS SR,
                   COALESCE(b.dismissal, 'not out') AS Dismissal
            FROM batting b
            JOIN matches m ON m.match_id = b.match_id
            JOIN match_players mp ON mp.match_id = b.match_id AND mp.team_id != b.team_id AND mp.player_id != b.player_id
            JOIN teams opp ON opp.team_id = mp.team_id
            WHERE b.player_id = %s
            GROUP BY m.match_date, opp.name, b.runs, b.balls, b.fours, b.sixes, b.dismissal, b.match_id
            ORDER BY m.match_date DESC""", (pid,))
        st.dataframe(inn, hide_index=True, width='stretch')

# ---------- bowling ----------
with tab_bowl:
    bowl = q("""
        SELECT cb.name AS Player, t.name AS Team, cb.innings AS Inns, cb.balls AS Balls,
               cb.runs AS Runs, cb.wickets AS Wkts, cb.economy AS Econ,
               ROUND(cb.runs*1.0/NULLIF(cb.wickets,0),2) AS Avg, cb.dots AS Dots,
               cb.player_id
        FROM career_bowling cb
        LEFT JOIN (SELECT DISTINCT player_id, team_id FROM match_players) mp ON mp.player_id = cb.player_id
        LEFT JOIN teams t ON t.team_id = mp.team_id
        ORDER BY cb.wickets DESC, cb.economy""")
    bowl["Overs"] = bowl["Balls"].map(overs)
    bowl["Dot%"] = (100.0 * bowl["Dots"] / bowl["Balls"]).round(1)
    f1, f2 = st.columns([2, 1])
    teams_b = ["All teams"] + sorted(bowl["Team"].dropna().unique().tolist())
    team_pick_b = f1.selectbox("Team", teams_b, key="bowl_team")
    min_wk = f2.slider("Minimum wickets", 0, int(bowl["Wkts"].max()), 0, 1)
    viewb = bowl[bowl["Wkts"] >= min_wk]
    if team_pick_b != "All teams":
        viewb = viewb[viewb["Team"] == team_pick_b]
    st.dataframe(viewb[["Player", "Team", "Inns", "Overs", "Runs", "Wkts", "Econ", "Avg", "Dot%"]],
                 hide_index=True, width='stretch', height=420)

    st.subheader("Player match by match")
    pickb = st.selectbox("Player", viewb["Player"].tolist(), key="bowl_player")
    if pickb:
        pidb = bowl.loc[bowl["Player"] == pickb, "player_id"].iloc[0]
        innb = q("""
            SELECT m.match_date AS Date, opp.name AS Against,
                   w.balls AS Balls, w.runs_conceded AS Runs, w.wickets AS Wkts,
                   w.dots AS Dots, ROUND(6.0*w.runs_conceded/NULLIF(w.balls,0),2) AS Econ
            FROM bowling w
            JOIN matches m ON m.match_id = w.match_id
            JOIN match_players mp ON mp.match_id = w.match_id AND mp.team_id != w.team_id AND mp.player_id != w.player_id
            JOIN teams opp ON opp.team_id = mp.team_id
            WHERE w.player_id = %s
            GROUP BY m.match_date, opp.name, w.balls, w.runs_conceded, w.wickets, w.dots, w.match_id
            ORDER BY m.match_date DESC""", (pidb,))
        innb["Overs"] = innb["Balls"].map(overs)
        st.dataframe(innb[["Date", "Against", "Overs", "Runs", "Wkts", "Dots", "Econ"]],
                     hide_index=True, width='stretch')

# ---------- matches ----------
with tab_matches:
    matches = q("""
        SELECT m.match_id, m.match_date, t1.name AS team1, t2.name AS team2,
               w.name AS winner, m.result_by, m.result_margin, m.venue, m.city
        FROM matches m
        JOIN teams t1 ON t1.team_id = m.team1_id
        JOIN teams t2 ON t2.team_id = m.team2_id
        LEFT JOIN teams w ON w.team_id = m.winner_id
        ORDER BY m.match_date DESC, m.match_id DESC""")
    matches["label"] = matches.apply(
        lambda r: f"{r['match_date']} · {r['team1']} vs {r['team2']}", axis=1)
    pick_m = st.selectbox("Match", matches["label"].tolist())
    row = matches.loc[matches["label"] == pick_m].iloc[0]
    mid = int(row["match_id"])
    st.markdown(f"**{result_text(row)}** · {row['venue']}" + (f", {row['city']}" if pd.notna(row['city']) else ""))

    for inn in (1, 2):
        bats = q("""
            SELECT p.name AS Batter,
                   CASE WHEN b.dismissal IS NULL THEN 'not out'
                        WHEN db.name IS NULL THEN b.dismissal
                        ELSE CONCAT(b.dismissal, ' (', db.name, ')') END AS `Out`,
                   b.runs AS R, b.balls AS B, b.fours AS `4s`, b.sixes AS `6s`,
                   ROUND(100.0*b.runs/NULLIF(b.balls,0),1) AS SR
            FROM batting b JOIN players p ON p.player_id = b.player_id
            LEFT JOIN players db ON db.player_id = b.dismissed_by_id
            WHERE b.match_id = %s AND b.innings = %s ORDER BY b.position""", (mid, inn))
        if bats.empty:
            continue
        bowls = q("""
            SELECT p.name AS Bowler, w.balls AS Balls, w.runs_conceded AS R,
                   w.wickets AS W, w.dots AS Dots, w.wides AS Wd, w.noballs AS Nb
            FROM bowling w JOIN players p ON p.player_id = w.player_id
            WHERE w.match_id = %s AND w.innings = %s""", (mid, inn))
        extras = int(bowls["Wd"].sum() + bowls["Nb"].sum())
        total = int(bats["R"].sum()) + extras
        wkts = int((bats["Out"] != "not out").sum())
        batting_team = q("""
            SELECT t.name FROM batting b JOIN teams t ON t.team_id = b.team_id
            WHERE b.match_id = %s AND b.innings = %s LIMIT 1""", (mid, inn))["name"][0]
        st.subheader(f"Innings {inn}: {batting_team} — {total}/{wkts} ({overs(bowls['Balls'].sum())} ov)")
        st.dataframe(bats, hide_index=True, width='stretch')
        bowls["Overs"] = bowls["Balls"].map(overs)
        bowls["Econ"] = (6.0 * bowls["R"] / bowls["Balls"]).round(2)
        st.dataframe(bowls[["Bowler", "Overs", "R", "W", "Dots", "Wd", "Nb", "Econ"]],
                     hide_index=True, width='stretch')
    st.caption("Totals exclude byes and leg-byes (not stored).")

# ---------- points table ----------
with tab_points:
    groups = q("SELECT DISTINCT COALESCE(event_group, 'Other') AS g FROM matches ORDER BY g")
    gpick = st.selectbox("Group", groups["g"].tolist())
    pts = q("""
        SELECT t.name AS Team,
               COUNT(*) AS P,
               SUM(CASE WHEN m.winner_id = t.team_id THEN 1 ELSE 0 END) AS W,
               SUM(CASE WHEN m.winner_id IS NOT NULL AND m.winner_id != t.team_id THEN 1 ELSE 0 END) AS L,
               SUM(CASE WHEN m.winner_id IS NULL THEN 1 ELSE 0 END) AS NR,
               SUM(CASE WHEN m.winner_id = t.team_id THEN 2 WHEN m.winner_id IS NULL THEN 1 ELSE 0 END) AS Pts
        FROM matches m
        JOIN teams t ON t.team_id IN (m.team1_id, m.team2_id)
        WHERE COALESCE(m.event_group, 'Other') = %s
        GROUP BY t.name ORDER BY Pts DESC, W DESC, Team""", (gpick,))
    st.dataframe(pts, hide_index=True, width='stretch')
    st.caption("2 points for a win. Net run rate not included.")

st.divider()
st.caption("Data © Cricsheet (cricsheet.org) · Stored on TiDB Cloud (MySQL-compatible) · Refreshed daily")
