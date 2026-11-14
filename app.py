import streamlit as st
st.set_page_config(
    page_title="Mars Walker: Gale Crater Planner",
    page_icon="🔴",
    layout="wide"
)

# CSS
st.markdown("""
<style>
    /* Main background color */
    .stApp {
        background-color: #0b0f19;
        color: #e2e8f0;
    }
    
    /* Custom headers */
    h1, h2, h3 {
        font-family: 'Courier New', Courier, monospace;
        color: #C0C0C0 !important; 
        letter-spacing: 1px;
    }
    
    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background-color: #111827;
        border-right: 1px solid #1e293b;
    }
    
    /* Custom buttons */
    .stButton>button {
        background: linear-gradient(90deg, #0284c7 0%, #0369a1 100%);
        color: white;
        border: 1px solid #38bdf8;
        font-family: 'Courier New', Courier, monospace;
        font-weight: bold;
        border-radius: 4px;
        transition: 0.3s ease;
    }
    
    .stButton>button:hover {
        background: linear-gradient(90deg, #0369a1 0%, #075985 100%);
        border-color: #7dd3fc;
        box-shadow: 0 0 10px rgba(56, 189, 248, 0.4);
    }
    
    /* Info boxes */
    .stAlert {
        background-color: #1e293b;
        color: #cbd5e1;
        border: 1px solid #334155;
    }
</style>
""", unsafe_allow_html=True)

if "page" not in st.session_state:
    st.session_state.page = "welcome"

def launch_planner():
    st.session_state.page = "planner"

def return_home():
    st.session_state.page = "welcome"

if st.session_state.page == "welcome":
    # --- WELCOME / LANDING PAGE ---
    st.title("Interplanetary Survival Map: Gale Crater")
    st.subheader("NASA Space Apps Hackathon 2026")
    
    st.markdown("---")
    
    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown("""# Welcome
        """)
    
        
        # Launch Button
        if st.button("Plan Route", type="primary", use_container_width=True):
            launch_planner()
            st.rerun()
            

elif st.session_state.page == "planner":
    # --- MAIN ROUTE PLANNER APP ---
    if st.button("Back"):
        return_home()
        st.rerun()
        
    st.title("Route visualization")
    
    # Sidebar filters
    max_slope = st.sidebar.slider("Max Allowable Slope (°)", 5, 30, 15, key = "topography")

    st.sidebar.header("Mineral Density")
    max_mineral_density = st.sidebar.slider("Max Allowable Mineral Density", 0, 100, 50, key = "minerals")

    st.sidebar.header("Radiation")
    max_mineral_density = st.sidebar.slider("Radiation Exposure", 0, 100, 50, key = "radiation")
