import streamlit as st

from astar_planner2 import (
    MAX_ROUGHNESS,
    build_terrain,
    create_route_figure,
    load_layers,
    plan_route,
    scale_cell,
    to_grid_path,
)
from map_picker import GRID_COLS, GRID_ROWS, pick_route_points

# Size of the A* grid (cells on the long side). Higher = finer route but slower A*.
ROUTE_GRID_TARGET = 800

st.set_page_config(
    page_title="Mars exploration route planner: Gale Crater",
    page_icon="*",
    layout="wide",
)

st.markdown(
    """
    <style>
    .stApp {
        background-color: #0b0f19;
        color: #e2e8f0;
    }

    h1, h2, h3 {
        font-family: Monaco, monospace;
        color: #c0c0c0 !important;
        letter-spacing: 1px;
    }

    [data-testid="stSidebar"] {
        background-color: #111827;
        border-right: 1px solid #1e293b;
    }

    .stButton > button {
        background: linear-gradient(90deg, #0284c7 0%, #0369a1 100%);
        color: white;
        border: 1px solid #38bdf8;
        font-family: "Courier New", Courier, monospace;
        font-weight: bold;
        border-radius: 4px;
    }

    .stAlert {
        background-color: #1e293b;
        color: #cbd5e1;
        border: 1px solid #334155;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

@st.cache_resource(show_spinner="Loading terrain and geology (first run only)...")
def get_layers(target):
    """Cache terrain layers."""
    return load_layers(target=target)


st.session_state.setdefault("page", "welcome")

if st.session_state.page == "welcome":
    st.title("Interplanetary Survival Map: Gale Crater")
    st.subheader("NASA Space Apps Hackathon 2026")

    combined_art = """
██▄  ▄██  ▄▄▄  ▄▄▄▄    ▄▄▄▄   ██████ ▄▄ ▄▄ ▄▄▄▄  ▄▄     ▄▄▄  ▄▄▄▄    ▄▄▄ ▄▄▄▄▄▄ ▄▄  ▄▄▄  ▄▄  ▄▄
██ ▀▀ ██ ██▀██ ██▄█▄ ███▄▄   ██▄▄   ▀█▄█▀ ██▄█▀ ██    ██▀██ ██▄█▄ ██▀██  ██   ██ ██▀██ ███▄██
██    ██ ██▀██ ██ ██ ▄▄██▀   ██▄▄▄▄  █ ██ ██    ██▄▄▄ ▀███▀ ██ ██ ██▀██  ██   ██ ▀███▀ ██ ▀██

█████▄   ▄▄▄  ▄▄ ▄▄ ▄▄▄▄▄▄ ▄▄▄▄▄   █████▄ ▄▄     ▄▄▄  ▄▄  ▄▄ ▄▄  ▄▄ ▄▄▄▄▄ ▄▄▄▄
██▄▄██▄ ██▀██ ██ ██   ██   ██▄▄    ██▄▄█▀ ██    ██▀██ ███▄██ ███▄██ ██▄▄  ██▄█▄
██  ██  ▀███▀ ▀███▀   ██   ██▄▄▄   ██     ██▄▄▄ ██▀██ ██ ▀██ ██ ▀██ ██▄▄▄ ██ ██
"""
    st.markdown(
        f"""
        <div style="font-family: monospace; color: orange; white-space: pre;
                    overflow-x: auto; line-height: 1.0;">{combined_art}</div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("Select Coordinates", type="primary", use_container_width=True):
        st.session_state.page = "planner"
        st.rerun()

elif st.session_state.page == "planner":
    if st.button("Back"):
        st.session_state.page = "welcome"
        st.rerun()

    st.title("Select Start and End Coordinates")
    st.caption(
        "Choose Start or End, then click the map. You can also enter latitude "
        "and longitude directly in the coordinate fields."
    )

    # ---- sidebar: these values feed the A* cost grid ----
    st.sidebar.header("Terrain Difficulty")
    terrain_difficulty = st.sidebar.slider(
        "How much terrain difficulty to consider", 1, 10, 5, key="terrain_difficulty",
        help="Higher = the route works harder to avoid slopes and rough ground.",
    )
    max_slope = st.sidebar.slider(
        "Max allowable slope (°)", 5, 30, 20, key="max_slope",
        help="Cells steeper than this are treated as impassable.",
    )
    max_roughness = st.sidebar.slider(
        "Max allowable roughness (m)",
        min_value=0.3,
        max_value=2.5,
        value=MAX_ROUGHNESS,
        step=0.1,
        key="max_roughness",
        help="Cells rougher than this are impassable. Raising it can make routes possible.",
    )
    st.sidebar.header("Geological Features of Interest")
    geo_interest = st.sidebar.slider(
        "How much to prioritise geologically interesting areas", 1, 10, 5, key="geo_interest",
        help="Higher = the route detours more to pass through high scientific-value ground.",
    )
    
    geology_weight = geo_interest * 0.6
    terrain_weight = terrain_difficulty / 5

    # ---- is there a finished route that still matches the current points and sliders? ----
    def route_key(s, e):
        return ((s["row"], s["col"]), (e["row"], e["col"]),
                max_slope, max_roughness, geo_interest, terrain_difficulty)

    saved_start, saved_end = st.session_state.get("start"), st.session_state.get("end")
    saved = st.session_state.get("route_result")
    route_is_current = bool(
        saved and saved_start and saved_end
        and saved["key"] == route_key(saved_start, saved_end)
    )
    route_error = st.session_state.pop("route_error", None)

    map_column, selection_column = st.columns([3, 2])
    with map_column:
        start, end = pick_route_points(
            "data/processed/cropped_dem.tif",
            display_width=650,
            path_cells=saved["map_path"] if route_is_current and saved["result"]["path"] else None,
        )

    with selection_column:
        st.subheader("Selected coordinates")
        if start:
            st.markdown("**Start**")
            st.write(f"Latitude: {start['lat']:.6f}°")
            st.write(f"Longitude: {start['lon']:.6f}°E")
            st.caption(f"Grid cell: row {start['row']}, column {start['col']}")
        else:
            st.info("Start point not selected.")

        if end:
            st.markdown("**End**")
            st.write(f"Latitude: {end['lat']:.6f}°")
            st.write(f"Longitude: {end['lon']:.6f}°E")
            st.caption(f"Grid cell: row {end['row']}, column {end['col']}")
        else:
            st.info("End point not selected.")

        if start and end:
            st.success("Both coordinates are selected.")
            if st.button(
                "Find optimal route",
                type="primary",
                use_container_width=True,
            ):
                try:
                    with st.spinner("Running A*..."):
                        layers = get_layers(ROUTE_GRID_TARGET)
                        terrain = build_terrain(
                            layers,
                            max_slope=max_slope,
                            geology_weight=geology_weight,
                            terrain_weight=terrain_weight,
                            max_roughness=max_roughness,
                        )
                        shape = terrain.shape
                        result = plan_route(
                            layers, terrain,
                            scale_cell((start["row"], start["col"]), (GRID_ROWS, GRID_COLS), shape),
                            scale_cell((end["row"], end["col"]), (GRID_ROWS, GRID_COLS), shape),
                        )
                    st.session_state.route_result = {
                        "key": route_key(start, end),
                        "result": result,
                        "figure": create_route_figure(layers, terrain, result) if result["path"] else None,
                        "map_path": (
                            to_grid_path(result["path"], shape, (GRID_ROWS, GRID_COLS))
                            if result["path"] else None
                        ),
                    }
                except (OSError, ValueError) as error:
                    st.session_state.route_error = str(error)
                    st.session_state.route_result = None
                st.rerun()

        if route_error:
            st.error(f"Could not calculate the route: {route_error}")

    # ---- results: metrics + matplotlib figure ----
    if route_is_current:
        result = saved["result"]
        st.divider()
        st.header("Optimal route")
        if result["path"] is None:
            st.warning(
                "No route is possible under the current hard slope and roughness limits. "
                "Try raising either limit or choosing different points. Terrain and geology "
                "weights change route preference, not which cells are passable."
            )
        else:
            stats = result["stats"]
            if result["moved_start"]:
                st.caption("Start moved to the nearest traversable cell.")
            if result["moved_goal"]:
                st.caption("End moved to the nearest traversable cell.")

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Route distance", f"{stats['length_km']:.2f} km")
            m2.metric("Straight-line", f"{stats['straight_km']:.2f} km",
                      f"{stats['detour_pct']:+.1f}% detour", delta_color="off")
            m3.metric("Mean science value", f"{stats['mean_science']:.2f}")
            m4.metric("Route in high-value geology", f"{stats['high_science_pct']:.0f}%")
            st.caption(f"Max slope on route: {stats['max_slope']:.1f}° · {stats['cells']} cells")

            st.pyplot(saved["figure"], width="stretch")