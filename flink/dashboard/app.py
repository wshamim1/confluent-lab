"""
dashboard/app.py — Live Streamlit dashboard for the local Flink pipeline.

Polls the FastAPI service every REFRESH_S seconds and renders:
  • Summary cards  — latest avg value + alert count per machine
  • Temperature chart — rolling avg_value per machine over time (Plotly line)
  • All sensors chart — faceted by sensor_type
  • Alerts table   — recent anomaly alerts with severity badges
  • Raw aggregates table

Run
---
    pip install streamlit plotly requests pandas
    streamlit run dashboard/app.py
"""

import os
import time

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

# ── Config ────────────────────────────────────────────────────────────────────

API_BASE  = os.getenv("API_BASE_URL", "http://localhost:8000")
REFRESH_S = int(os.getenv("DASHBOARD_REFRESH_S", "5"))

SEVERITY_COLOUR = {
    "critical": "#ef4444",
    "warning":  "#f59e0b",
    "info":     "#3b82f6",
    "normal":   "#22c55e",
}

st.set_page_config(
    page_title="Local Flink Pipeline",
    page_icon="⚡",
    layout="wide",
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _get(path: str, params: dict | None = None) -> list[dict]:
    try:
        r = requests.get(f"{API_BASE}{path}", params=params, timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        st.warning(f"API error ({path}): {exc}")
        return []


def _badge(severity: str) -> str:
    colour = SEVERITY_COLOUR.get(severity, "#6b7280")
    return (
        f'<span style="background:{colour};color:#fff;padding:2px 8px;'
        f'border-radius:4px;font-size:12px;font-weight:600;">'
        f'{severity.upper()}</span>'
    )


# ── Layout ────────────────────────────────────────────────────────────────────

st.title("⚡ Local Flink Pipeline — Live Dashboard")
st.caption(
    f"Python Producer → Kafka → Flink → PostgreSQL → FastAPI → Streamlit  |  "
    f"API: `{API_BASE}`  |  Refreshing every {REFRESH_S}s"
)

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("Controls")
    refresh = st.toggle("Auto-refresh", value=True)
    sev_filter = st.selectbox(
        "Alert severity filter",
        options=["all", "critical", "warning", "info"],
        index=0,
    )
    machine_filter = st.selectbox(
        "Machine filter",
        options=["all", "turbine-1", "compressor-1", "pump-1", "hvac-1"],
        index=0,
    )
    st.markdown("---")
    st.markdown("**Stack**")
    st.markdown(
        "- 🟠 Kafka (KRaft)\n"
        "- 🔵 Flink 1.20\n"
        "- 🐘 PostgreSQL\n"
        "- ⚡ FastAPI\n"
        "- 📊 Streamlit"
    )
    st.markdown("---")
    if st.button("🔄 Refresh now"):
        st.rerun()

# ── Fetch data ────────────────────────────────────────────────────────────────

summary_data  = _get("/summary")
alerts_data   = _get(
    "/alerts",
    params={"limit": 50, **({"severity": sev_filter} if sev_filter != "all" else {})},
)
sensors_data  = _get(
    f"/sensors/{machine_filter}" if machine_filter != "all" else "/sensors",
    params={"limit": 200},
)

# ── Summary cards ─────────────────────────────────────────────────────────────

st.subheader("Machine Overview")

if summary_data:
    machines = {}
    for row in summary_data:
        m = row["machine_id"]
        if m not in machines:
            machines[m] = {"alert_count": row.get("alert_count", 0),
                           "worst_severity": row.get("worst_severity", "normal"),
                           "sensors": []}
        machines[m]["sensors"].append(row)

    cols = st.columns(len(machines))
    for col, (machine_id, info) in zip(cols, machines.items()):
        sev   = info["worst_severity"] or "normal"
        color = SEVERITY_COLOUR.get(sev, "#22c55e")
        with col:
            st.markdown(
                f"""
                <div style="border:1px solid {color};border-radius:8px;padding:12px;
                            background:#f8fafc;margin-bottom:8px;">
                  <div style="font-weight:700;font-size:15px;">{machine_id}</div>
                  <div style="color:#57606a;font-size:12px;">{info['sensors'][0].get('facility','')}</div>
                  <div style="margin-top:8px;">
                    <span style="font-size:22px;font-weight:700;color:{color};">
                      {info['alert_count']}
                    </span>
                    <span style="font-size:12px;color:#57606a;"> alerts (last 1h)</span>
                  </div>
                  <div style="margin-top:4px;">{_badge(sev)}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
else:
    st.info("No summary data yet — waiting for Flink to write aggregates to PostgreSQL.")

st.markdown("---")

# ── Sensor charts ─────────────────────────────────────────────────────────────

st.subheader("Sensor Aggregates Over Time")

if sensors_data:
    df = pd.DataFrame(sensors_data)
    df["window_start"] = pd.to_datetime(df["window_start"])

    tab1, tab2 = st.tabs(["By Machine (avg)", "By Sensor Type"])

    with tab1:
        fig = px.line(
            df,
            x="window_start",
            y="avg_value",
            color="machine_id",
            facet_col="sensor_type",
            facet_col_wrap=3,
            labels={"window_start": "Window", "avg_value": "Avg Value"},
            title="Average Sensor Value per Machine per Window",
            height=500,
        )
        fig.update_layout(margin=dict(t=60, b=20))
        st.plotly_chart(fig, use_container_width=True)

    with tab2:
        sensor_types = df["sensor_type"].unique().tolist()
        chosen = st.multiselect("Sensor types", sensor_types, default=sensor_types[:2])
        filtered = df[df["sensor_type"].isin(chosen)] if chosen else df
        fig2 = px.line(
            filtered,
            x="window_start",
            y="avg_value",
            color="machine_id",
            line_dash="sensor_type",
            labels={"window_start": "Window", "avg_value": "Avg Value"},
            title="Average Value by Sensor Type",
            height=400,
        )
        st.plotly_chart(fig2, use_container_width=True)
else:
    st.info("No sensor aggregate data yet.")

st.markdown("---")

# ── Alerts table ──────────────────────────────────────────────────────────────

st.subheader("Anomaly Alerts")

if alerts_data:
    df_alerts = pd.DataFrame(alerts_data)
    df_alerts["detected_at"] = pd.to_datetime(df_alerts["detected_at"])
    df_alerts = df_alerts.sort_values("detected_at", ascending=False)

    # Render severity as HTML badge
    html_rows = []
    for _, row in df_alerts.head(20).iterrows():
        html_rows.append(
            f"<tr>"
            f"<td>{row['detected_at'].strftime('%H:%M:%S')}</td>"
            f"<td><b>{row['machine_id']}</b></td>"
            f"<td>{row['sensor_type']}</td>"
            f"<td>{row.get('avg_value', 0):.2f} {row.get('unit', '')}</td>"
            f"<td>{row.get('anomaly_score', 0):.3f}</td>"
            f"<td>{_badge(row['severity'])}</td>"
            f"</tr>"
        )
    table_html = (
        "<table style='width:100%;border-collapse:collapse;font-size:13px;'>"
        "<thead><tr style='background:#f0f4f8;'>"
        "<th style='padding:6px;text-align:left;'>Time</th>"
        "<th style='padding:6px;text-align:left;'>Machine</th>"
        "<th style='padding:6px;text-align:left;'>Sensor</th>"
        "<th style='padding:6px;text-align:left;'>Avg Value</th>"
        "<th style='padding:6px;text-align:left;'>Score</th>"
        "<th style='padding:6px;text-align:left;'>Severity</th>"
        "</tr></thead>"
        "<tbody>" + "".join(html_rows) + "</tbody>"
        "</table>"
    )
    st.markdown(table_html, unsafe_allow_html=True)

    with st.expander("Raw alert data"):
        st.dataframe(df_alerts, use_container_width=True)
else:
    st.success("✅ No alerts matching current filter.")

st.markdown("---")

# ── Raw aggregates ────────────────────────────────────────────────────────────

with st.expander("Raw sensor aggregates"):
    if sensors_data:
        st.dataframe(pd.DataFrame(sensors_data), use_container_width=True)
    else:
        st.info("No data.")

# ── Auto-refresh ──────────────────────────────────────────────────────────────

if refresh:
    time.sleep(REFRESH_S)
    st.rerun()
