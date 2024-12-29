import streamlit as st


# Set page configuration
st.set_page_config(layout="wide", page_title="Race & Training Planner")

import requests
from datetime import datetime, timedelta, date
import pandas as pd
import altair as alt
import logging
import os
from dotenv import load_dotenv
from snowflake.snowpark.session import Session
from snowflake.snowpark.functions import col
from streamlit_cookies_manager import EncryptedCookieManager
import uuid
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.dates as mdates
import threading
from queue import Queue
import json
import time
from collections import defaultdict
from streamlit.runtime.scriptrunner import add_script_run_ctx,get_script_run_ctx



# from streamlit_vega_lite import vega_lite_events
logging.basicConfig(filename="output.log", level=logging.INFO)

# Load local environment variables if running locally
if not st.secrets:
    load_dotenv()

custom_css = """
<style>
/* Remove margin on the main container */
section.main > div.stMainBlockContainer {
    margin-top: 0px !important;
    padding-top: 0px !important;
}

/* Remove padding above all Streamlit containers */
div.withScreencast > div > div > section > div.stMainBlockContainer {
    margin-top: 20px !important;
    padding-top: 0px !important;
}

/* Completely hide iframe for cookies */
iframe[title="streamlit_cookies_manager.cookie_manager.CookieManager.sync_cookies"] {
    display: none !important;
}
</style>
"""

# Inject the custom CSS
st.markdown(custom_css, unsafe_allow_html=True)


# else:
#     # st.warning("Cookies are not ready or supported!")
#     pass
STRAVA_API_URL = "https://www.strava.com/api/v3"
# Use Streamlit secrets management
client_id = st.secrets.get("strava", {}).get("client_id", os.getenv("STRAVA_CLIENT_ID"))
client_secret = st.secrets.get("strava", {}).get("client_secret", os.getenv("STRAVA_CLIENT_SECRET"))
redirect_uri = st.secrets.get("strava", {}).get("redirect_uri", os.getenv("STRAVA_REDIRECT_URI"))
scopes = "read,activity:read_all,activity:write"

imgur_client_id = st.secrets.get("imgur", {}).get("client_id", os.getenv("IMGUR_CLIENT_ID"))
imgur_client_secret = st.secrets.get("imgur", {}).get("client_secret", os.getenv("IMGUR_CLIENT_SECRET"))

connection_parameters = {
    "account": st.secrets.get("snowflake", {}).get("account", os.getenv("SNOWFLAKE_ACCOUNT")),
    "user": st.secrets.get("snowflake", {}).get("user", os.getenv("SNOWFLAKE_USER")),
    "password": st.secrets.get("snowflake", {}).get("password", os.getenv("SNOWFLAKE_PASSWORD")),
    "role": st.secrets.get("snowflake", {}).get("role", os.getenv("SNOWFLAKE_ROLE")),
    "warehouse": st.secrets.get("snowflake", {}).get("warehouse", os.getenv("SNOWFLAKE_WAREHOUSE")),
    "database": st.secrets.get("snowflake", {}).get("database", os.getenv("SNOWFLAKE_DATABASE")),
    "schema": st.secrets.get("snowflake", {}).get("schema", os.getenv("SNOWFLAKE_SCHEMA")),
}

# Initialize session state
if "db_sync_status" not in st.session_state:
    st.session_state["db_sync_status"] = "pending"

if "result_queue" not in st.session_state:
    st.session_state["result_queue"] = Queue()


def log_debug(message):
    logging.debug(message)


def log_info(message):
    # add timestamp to message
    message = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}"
    logging.info(message)


def log_error(message):
    logging.error(message)

def log_warning(message):
    logging.warning(message)
    
def get_or_create_session_id(cookies):
    # Generate a temporary session ID
    session_id = str(uuid.uuid4())
    timeout = 5  # Timeout in seconds to wait for cookies to be ready
    interval = 0.1  # Interval to check readiness

    start_time = time.time()
    while not cookies.ready():
        if time.time() - start_time > timeout:
            log_warning("Cookies not ready, using temporary session ID.")
            return session_id  # Return the temporary session ID after timeout
        time.sleep(interval)

    # Overwrite the temporary session ID with the one from the cookies
    if "session_id" not in cookies:
        cookies["session_id"] = session_id
        cookies.save()
    else:
        session_id = cookies["session_id"]

    return session_id
cookies = EncryptedCookieManager(
    prefix="my_app",  # Replace with your app's name or namespace
    password="supersecret",  # Ensure this is secure
)

session_id = get_or_create_session_id(cookies)
log_info(f"Session ID: {session_id}")

def create_snowflake_session(connection_parameters):
    """
    Create or refresh a Snowflake session.
    """
    try:
        session = Session.builder.configs(connection_parameters).create()
        return session
    except ProgrammingError as e:
        if "Authentication token has expired" in str(e):
            log_info("Snowflake token has expired. Reauthenticating...")
            # Retry session creation
            session = Session.builder.configs(connection_parameters).create()
            return session
        else:
            log_error(f"Failed to create Snowflake session: {e}")
            raise

def final_date(d):
    return d if isinstance(d, date) and not isinstance(d, datetime) else d.date()

# Function to convert seconds to HH:MM:SS format
def seconds_to_hhmmss(seconds):
    return str(timedelta(seconds=int(seconds)))

# Update the Y-axis ticks dynamically
def format_y_ticks(max_seconds):
    max_seconds = int(max_seconds)
    ticks = [i for i in range(0, max_seconds + 1, max_seconds // 5)]  # 5 ticks
    return {tick: seconds_to_hhmmss(tick) for tick in ticks}

# Update the X-axis ticks dynamically
def format_x_ticks(max_seconds):
    max_seconds = int(max_seconds)
    ticks = [i for i in range(0, max_seconds + 1, max_seconds // 5)]  # 5 ticks
    return {tick: seconds_to_hhmmss(tick) for tick in ticks}

ATHLETE_LEVELS = ["Beginner", "Intermediate", "Confirmed"]

TRAINING_SPORTS = ["Run", "Bike"]

CYCLE_TYPES = ["Transition", "Fondamental", "Specific", "Pre-Compet", "Compet"]

OBJECTIVE_SIZE = ["S", "M", "L", "XL"]

OBJECTIVE_RACE = ["Finish", "Perf"]

WEEK_DAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

ZONES = {
    "Run": {
        1: "Active Recovery",
        2: "Endurance",
        3: "Tempo",
        4: "Lactate Threshold",
        5: "VO2 Max",
        6: "Anaerobic Capacity",
        7: "Neuromuscular Power",
    },
    "Bike": {
        1: "Active Recovery",
        2: "Endurance",
        3: "Tempo",
        4: "Lactate Threshold",
        5: "VO2 Max",
        6: "Anaerobic Capacity",
        7: "Neuromuscular Power",
    },
}

TSS_BY_ZONE_BY_SPORT = {
    "Run": {1: 50, 2: 60, 3: 80, 4: 100, 5: 150, 6: 250, 7: 500},
    "Bike": {1: 50, 2: 60, 3: 80, 4: 100, 5: 150, 6: 250, 7: 500},
}

ZONE_RECOVERY_FACTOR_BY_SPORT = {
    "Run": {1: 0, 2: 0.2, 3: 0.5, 4: 0.75, 5: 1, 6: 2, 7: 20},
    "Bike": {1: 0, 2: 0.2, 3: 0.5, 4: 0.75, 5: 1, 6: 2, 7: 20},
}

TYPICAL_DURATION_FOR_INTERVALS_BY_ZONE_BY_SPORT = {
    "Run": {1: 3600, 2: 3600, 3: 1200, 4: 600, 5: 180, 6: 60, 7: 12},
    "Bike": {1: 3600, 2: 3600, 3: 1200, 4: 600, 5: 180, 6: 60, 7: 12},
}

SPEED_BY_ZONE_BY_SPORT_BY_ATHLETE_LEVEL_KMH = {
    "Run": {
        "Beginner": {1: 8, 2: 9, 3: 11, 4: 12, 5: 13, 6: 14, 7: 20},
        "Intermediate": {1: 9, 2: 10, 3: 12, 4: 14, 5: 16, 6: 18, 7: 24},
        "Confirmed": {1: 10, 2: 11, 3: 13, 4: 15, 5: 17, 6: 19, 7: 26},
    },
    "Bike": {
        "Beginner": {1: 18, 2: 22, 3: 26, 4: 29, 5: 33, 6: 38, 7: 45},
        "Intermediate": {1: 22, 2: 26, 3: 30, 4: 34, 5: 38, 6: 42, 7: 50},
        "Confirmed": {1: 26, 2: 30, 3: 34, 4: 38, 5: 42, 6: 46, 7: 55},
    },
}

LONG_WORKOUT_TSS_BY_SPORT_BY_OBJECTIVE_BY_OBJECTIVE_SIZE_BY_ATHLETE_LEVEL_PERCENTAGE_OF_RACE = {
    "Run": {
        "Finish": {
            "S": {"Beginner": 0.75, "Intermediate": 0.75, "Confirmed": 0.75},
            "M": {"Beginner": 0.75, "Intermediate": 0.75, "Confirmed": 0.75},
            "L": {"Beginner": 0.75, "Intermediate": 0.75, "Confirmed": 0.75},
            "XL": {"Beginner": 0.65, "Intermediate": 0.65, "Confirmed": 0.65},
        },
        "Perf": {
            "S": {"Beginner": 1.3, "Intermediate": 1.7, "Confirmed": 2},
            "M": {"Beginner": 0.9, "Intermediate": 1.1, "Confirmed": 1.5},
            "L": {"Beginner": 0.65, "Intermediate": 0.75, "Confirmed": 0.85},
            "XL": {"Beginner": 0.65, "Intermediate": 0.70, "Confirmed": 0.75},
        },
    },
    "Bike": {
        "Finish": {
            "S": {"Beginner": 0.75, "Intermediate": 0.75, "Confirmed": 0.75},
            "M": {"Beginner": 0.75, "Intermediate": 0.75, "Confirmed": 0.75},
            "L": {"Beginner": 0.75, "Intermediate": 0.75, "Confirmed": 0.75},
            "XL": {"Beginner": 0.65, "Intermediate": 0.65, "Confirmed": 0.65},
        },
        "Perf": {
            "S": {"Beginner": 1.3, "Intermediate": 1.7, "Confirmed": 2},
            "M": {"Beginner": 0.9, "Intermediate": 1.1, "Confirmed": 1.5},
            "L": {"Beginner": 0.65, "Intermediate": 0.75, "Confirmed": 0.85},
            "XL": {"Beginner": 0.65, "Intermediate": 0.70, "Confirmed": 0.75},
        },
    },
}


RACE_INTENSITY_WORKOUT_TSS_BY_SPORT_BY_OBJECTIVE_BY_OBJECTIVE_SIZE_BY_ATHLETE_LEVEL_PERCENTAGE_OF_RACE = {
    "Run": {
        "Finish": {
            "S": {"Beginner": 0.75, "Intermediate": 0.75, "Confirmed": 0.75},
            "M": {"Beginner": 0.75, "Intermediate": 0.75, "Confirmed": 0.75},
            "L": {"Beginner": 0.75, "Intermediate": 0.75, "Confirmed": 0.75},
            "XL": {"Beginner": 0.65, "Intermediate": 0.65, "Confirmed": 0.65},
        },
        "Perf": {
            "S": {"Beginner": 0.8, "Intermediate": 0.8, "Confirmed": 0.8},
            "M": {"Beginner": 0.75, "Intermediate": 0.75, "Confirmed": 0.75},
            "L": {"Beginner": 0.55, "Intermediate": 0.55, "Confirmed": 0.55},
            "XL": {"Beginner": 0.40, "Intermediate": 0.40, "Confirmed": 0.40},
        },
    },
    "Bike": {
        "Finish": {
            "S": {"Beginner": 0.75, "Intermediate": 0.75, "Confirmed": 0.75},
            "M": {"Beginner": 0.75, "Intermediate": 0.75, "Confirmed": 0.75},
            "L": {"Beginner": 0.75, "Intermediate": 0.75, "Confirmed": 0.75},
            "XL": {"Beginner": 0.65, "Intermediate": 0.65, "Confirmed": 0.65},
        },
        "Perf": {
            "S": {"Beginner": 0.8, "Intermediate": 0.8, "Confirmed": 0.8},
            "M": {"Beginner": 0.75, "Intermediate": 0.75, "Confirmed": 0.75},
            "L": {"Beginner": 0.55, "Intermediate": 0.55, "Confirmed": 0.55},
            "XL": {"Beginner": 0.40, "Intermediate": 0.40, "Confirmed": 0.40},
        },
    },
}


REGULAR_MAX_WORKOUT_TSS_BY_SPORT_BY_OBJECTIVE_BY_OBJECTIVE_SIZE_BY_ATHLETE_LEVEL = {
    "Run": {
        "Finish": {
            "S": {"Beginner": 70, "Intermediate": 80, "Confirmed": 90},
            "M": {"Beginner": 120, "Intermediate": 140, "Confirmed": 160},
            "L": {"Beginner": 170, "Intermediate": 200, "Confirmed": 230},
            "XL": {"Beginner": 230, "Intermediate": 270, "Confirmed": 320},
        },
        "Perf": {
            "S": {"Beginner": 100, "Intermediate": 120, "Confirmed": 150},
            "M": {"Beginner": 150, "Intermediate": 180, "Confirmed": 200},
            "L": {"Beginner": 250, "Intermediate": 250, "Confirmed": 280},
            "XL": {"Beginner": 350, "Intermediate": 320, "Confirmed": 350},
        },
    },
    "Bike": {
        "Finish": {
            "S": {"Beginner": 70, "Intermediate": 80, "Confirmed": 90},
            "M": {"Beginner": 120, "Intermediate": 140, "Confirmed": 160},
            "L": {"Beginner": 170, "Intermediate": 200, "Confirmed": 230},
            "XL": {"Beginner": 230, "Intermediate": 270, "Confirmed": 320},
        },
        "Perf": {
            "S": {"Beginner": 100, "Intermediate": 120, "Confirmed": 150},
            "M": {"Beginner": 150, "Intermediate": 180, "Confirmed": 200},
            "L": {"Beginner": 250, "Intermediate": 250, "Confirmed": 280},
            "XL": {"Beginner": 350, "Intermediate": 320, "Confirmed": 350},
        },
    },
}

REGULAR_WORKOUT_TSS_BY_SPORT_BY_OBJECTIVE_BY_OBJECTIVE_SIZE_BY_ATHLETE_LEVEL = {
    "Run": {
        "Finish": {
            "S": {"Beginner": 45, "Intermediate": 60, "Confirmed": 75},
            "M": {"Beginner": 55, "Intermediate": 70, "Confirmed": 85},
            "L": {"Beginner": 65, "Intermediate": 80, "Confirmed": 95},
            "XL": {"Beginner": 75, "Intermediate": 82, "Confirmed": 90},
        },
        "Perf": {
            "S": {"Beginner": 60, "Intermediate": 70, "Confirmed": 80},
            "M": {"Beginner": 70, "Intermediate": 80, "Confirmed": 90},
            "L": {"Beginner": 80, "Intermediate": 90, "Confirmed": 100},
            "XL": {"Beginner": 90, "Intermediate": 100, "Confirmed": 110},
        },
    },
    "Bike": {
        "Finish": {
            "S": {"Beginner": 45, "Intermediate": 60, "Confirmed": 75},
            "M": {"Beginner": 55, "Intermediate": 70, "Confirmed": 85},
            "L": {"Beginner": 65, "Intermediate": 80, "Confirmed": 95},
            "XL": {"Beginner": 75, "Intermediate": 82, "Confirmed": 90},
        },
        "Perf": {
            "S": {"Beginner": 60, "Intermediate": 70, "Confirmed": 80},
            "M": {"Beginner": 70, "Intermediate": 80, "Confirmed": 90},
            "L": {"Beginner": 80, "Intermediate": 90, "Confirmed": 100},
            "XL": {"Beginner": 90, "Intermediate": 100, "Confirmed": 110},
        },
    },
}

MAX_TSS_PER_DAY_BY_SPORT_BY_OBJECTIVE_BY_OBJECTIVE_SIZE_BY_ATHLETE_LEVEL = {
    "Run": {
        "Finish": {
            "S": {"Beginner": 70, "Intermediate": 80, "Confirmed": 90},
            "M": {"Beginner": 120, "Intermediate": 140, "Confirmed": 160},
            "L": {"Beginner": 170, "Intermediate": 200, "Confirmed": 230},
            "XL": {"Beginner": 230, "Intermediate": 270, "Confirmed": 320},
        },
        "Perf": {
            "S": {"Beginner": 100, "Intermediate": 120, "Confirmed": 150},
            "M": {"Beginner": 150, "Intermediate": 180, "Confirmed": 200},
            "L": {"Beginner": 250, "Intermediate": 250, "Confirmed": 280},
            "XL": {"Beginner": 350, "Intermediate": 320, "Confirmed": 350},
        },
    },
    "Bike": {
        "Finish": {
            "S": {"Beginner": 70, "Intermediate": 80, "Confirmed": 90},
            "M": {"Beginner": 120, "Intermediate": 140, "Confirmed": 160},
            "L": {"Beginner": 170, "Intermediate": 200, "Confirmed": 230},
            "XL": {"Beginner": 230, "Intermediate": 270, "Confirmed": 320},
        },
        "Perf": {
            "S": {"Beginner": 100, "Intermediate": 120, "Confirmed": 150},
            "M": {"Beginner": 150, "Intermediate": 180, "Confirmed": 200},
            "L": {"Beginner": 250, "Intermediate": 250, "Confirmed": 280},
            "XL": {"Beginner": 350, "Intermediate": 320, "Confirmed": 350},
        },
    },
}


MAX_CYCLES_TIMING_DAYS_TO_RACE_BY_OBJECTIVE_BY_OBJECTIVE_SIZE = {
    "Perf": {
        "S": {
            "Fondamental": 365,
            "Specific": 90,
            "Pre-Compet": 0,
            "Compet": 7,
            "Transition": 0,
        },
        "M": {
            "Fondamental": 365,
            "Specific": 90,
            "Pre-Compet": 7,
            "Compet": 7,
            "Transition": 0,
        },
        "L": {
            "Fondamental": 365,
            "Specific": 90,
            "Pre-Compet": 7,
            "Compet": 7,
            "Transition": 0,
        },
        "XL": {
            "Fondamental": 720,
            "Specific": 90,
            "Pre-Compet": 7,
            "Compet": 7,
            "Transition": 0,
        },
    },
    "Finish": {
        "S": {
            "Fondamental": 365,
            "Specific": 90,
            "Pre-Compet": 7,
            "Compet": 7,
            "Transition": 0,
        },
        "M": {
            "Fondamental": 365,
            "Specific": 90,
            "Pre-Compet": 7,
            "Compet": 7,
            "Transition": 0,
        },
        "L": {
            "Fondamental": 365,
            "Specific": 90,
            "Pre-Compet": 7,
            "Compet": 7,
            "Transition": 0,
        },
        "XL": {
            "Fondamental": 720,
            "Specific": 90,
            "Pre-Compet": 7,
            "Compet": 7,
            "Transition": 0,
        },
    },
}

COMPET_CYCLE_TSS_MULTIPLICATOR_BY_SPORT_BY_OBJECTIVE_OBJECTIVE_SIZE = {
    "Run": {
        "Perf": {"S": 1.5, "M": 1.5, "L": 1.5, "XL": 1.5},
        "Finish": {"S": 1.5, "M": 1.5, "L": 1.5, "XL": 1.5},
    },
    "Bike": {
        "Perf": {"S": 1.5, "M": 1.5, "L": 1.5, "XL": 1.5},
        "Finish": {"S": 1.5, "M": 1.5, "L": 1.5, "XL": 1.5},
    },
}

ZONE_REPARTITION_BY_TIME_BY_WEEK_BY_CYCLE = {
    "Confirmed": {
        "Fondamental": {
            "S": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
            "M": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
            "L": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
            "XL": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
        },
        "Specific": {
            "S": {1: 0.4, 2: 0.2, 3: 0.2, 4: 0.12, 5: 0.06, 6: 0.02, 7: 0.00},
            "M": {1: 0.4, 2: 0.25, 3: 0.2, 4: 0.1, 5: 0.03, 6: 0.02, 7: 0.00},
            "L": {1: 0.4, 2: 0.30, 3: 0.15, 4: 0.1, 5: 0.03, 6: 0.02, 7: 0.00},
            "XL": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
        },
        "Pre-Compet": {
            "S": {1: 0.4, 2: 0.2, 3: 0.2, 4: 0.12, 5: 0.06, 6: 0.02, 7: 0.00},
            "M": {1: 0.4, 2: 0.25, 3: 0.2, 4: 0.1, 5: 0.03, 6: 0.02, 7: 0.00},
            "L": {1: 0.4, 2: 0.30, 3: 0.15, 4: 0.1, 5: 0.03, 6: 0.02, 7: 0.00},
            "XL": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
        },
        "Compet": {
            "S": {1: 0.4, 2: 0.2, 3: 0.2, 4: 0.12, 5: 0.06, 6: 0.02, 7: 0.00},
            "M": {1: 0.4, 2: 0.25, 3: 0.2, 4: 0.1, 5: 0.03, 6: 0.02, 7: 0.00},
            "L": {1: 0.4, 2: 0.30, 3: 0.15, 4: 0.1, 5: 0.03, 6: 0.02, 7: 0.00},
            "XL": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
        },
        "Transition": {
            "S": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
            "M": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
            "L": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
            "XL": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
        },
    },
    "Beginner": {
        "Fondamental": {
            "S": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
            "M": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
            "L": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
            "XL": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
        },
        "Specific": {
            "S": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
            "M": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
            "L": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
            "XL": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
        },
        "Pre-Compet": {
            "S": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
            "M": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
            "L": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
            "XL": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
        },
        "Compet": {
            "S": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
            "M": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
            "L": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
            "XL": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
        },
        "Transition": {
            "S": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
            "M": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
            "L": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
            "XL": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
        },
    },
    "Intermediate": {
        "Fondamental": {
            "S": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
            "M": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
            "L": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
            "XL": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
        },
        "Specific": {
            "S": {1: 0.4, 2: 0.25, 3: 0.2, 4: 0.1, 5: 0.03, 6: 0.02, 7: 0.00},
            "M": {1: 0.4, 2: 0.30, 3: 0.15, 4: 0.1, 5: 0.03, 6: 0.02, 7: 0.00},
            "L": {1: 0.4, 2: 0.35, 3: 0.13, 4: 0.07, 5: 0.03, 6: 0.02, 7: 0.00},
            "XL": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
        },
        "Pre-Compet": {
            "S": {1: 0.4, 2: 0.25, 3: 0.2, 4: 0.1, 5: 0.03, 6: 0.02, 7: 0.00},
            "M": {1: 0.4, 2: 0.30, 3: 0.15, 4: 0.1, 5: 0.03, 6: 0.02, 7: 0.00},
            "L": {1: 0.4, 2: 0.35, 3: 0.13, 4: 0.07, 5: 0.03, 6: 0.02, 7: 0.00},
            "XL": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
        },
        "Compet": {
            "S": {1: 0.4, 2: 0.25, 3: 0.2, 4: 0.1, 5: 0.03, 6: 0.02, 7: 0.00},
            "M": {1: 0.4, 2: 0.30, 3: 0.15, 4: 0.1, 5: 0.03, 6: 0.02, 7: 0.00},
            "L": {1: 0.4, 2: 0.35, 3: 0.13, 4: 0.07, 5: 0.03, 6: 0.02, 7: 0.00},
            "XL": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
        },
        "Transition": {
            "S": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
            "M": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
            "L": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
            "XL": {1: 0.4, 2: 0.4, 3: 0.1, 4: 0.05, 5: 0.03, 6: 0.02, 7: 0.00},
        },
    },
}

KEY_WORKOUTS_BY_CYCLE = {
    "Fondamental": ["LongIntensity"],
    "Specific": ["Long", "RaceIntensity"],
    "Pre-Compet": ["ShortIntensity", "RaceIntensity"],
    "Compet": [],
    "Transition": ["Long", "Tempo"],
}


def determineEventSize(distance, sport, duration=None):
    if sport == "Run":
        if distance <= 12:
            return "S"
        elif distance <= 23:
            return "M"
        elif distance <= 45:
            return "L"
        else:
            return "XL"
    elif sport == "Bike":
        if distance <= 40:
            return "S"
        elif distance <= 80:
            return "M"
        elif distance <= 130:
            return "L"
        else:
            return "XL"


def determineRaceZone(eventSize, objective):
    if objective == "Finish":
        return 2
    elif objective == "Perf":
        if eventSize == "S":
            return 5
        elif eventSize == "M":
            return 4
        elif eventSize == "L":
            return 3
        else:
            return 2


def calculateEventTss(raceZone, sport, targetTimeInMinutes):
    return TSS_BY_ZONE_BY_SPORT[sport][raceZone] * targetTimeInMinutes / 60


def computeFondamentalWeeksRequired(
    currentLoad,
    currentCycleNumber,
    currentIndexInCycle,
    endLoad,
    weeklyTssIncreaseRate,
    cycleLength,
    nextRestingWeek,
    lastWeeksTakeways,
):
    workingLoads = []
    indexInCycle = currentIndexInCycle
    cycleNumber = currentCycleNumber

    if currentLoad < endLoad * 0.95:
        while True:
            if nextRestingWeek == 0:
                indexInCycle += 1
                restingLoad = currentLoad * 0.6
                workingLoads.append(
                    {
                        "theoreticalWeeklyTSS": int(restingLoad),
                        "theoreticalResting": True,
                        "cycleNumber": cycleNumber,
                        "indexInCycle": indexInCycle,
                    }
                )
                # After inserting a resting week, now set nextRestingWeek to cycleLength - 1
                nextRestingWeek = cycleLength - 1
                cycleNumber += 1
                indexInCycle = 0
            else:
                # Working week logic
                currentLoad *= 1 + weeklyTssIncreaseRate
                indexInCycle += 1
                workingLoads.append(
                    {
                        "theoreticalWeeklyTSS": min(endLoad, int(currentLoad)),
                        "theoreticalResting": False,
                        "cycleNumber": cycleNumber,
                        "indexInCycle": indexInCycle,
                        "keyWorkouts": KEY_WORKOUTS_BY_CYCLE["Fondamental"],
                    }
                )
                nextRestingWeek -= 1
                if currentLoad > endLoad * 0.95:
                    break

    for week in workingLoads:
        week["cycleType"] = "Fondamental"
    return workingLoads, nextRestingWeek, cycleNumber


def analyzeMacrocycle(macrocycle, completedWorkouts, raceZone, mainSport):
    pass


def checkWorkoutValidity(actualWorkout, theoreticalWorkout):
    if actualWorkout["activity"] != theoreticalWorkout["activity"]:
        return 0
    if theoreticalWorkout["workoutType"] == "Long":
        if actualWorkout["tss"] > theoreticalWorkout["tss"] * 0.8:
            actualWorkout["workoutType"] = "Long"
            return 1
        else:
            return 0
    if theoreticalWorkout["workoutType"] == "LongIntensity":
        if (
            actualWorkout["secondsInZone"][4]
            * 3600
            * TSS_BY_ZONE_BY_SPORT[actualWorkout["activity"]][4]
            + actualWorkout["secondsInZone"][3]
            * 3600
            * TSS_BY_ZONE_BY_SPORT[actualWorkout["activity"]][3]
            > theoreticalWorkout["tss"] * 0.8
        ):
            actualWorkout["workoutType"] = "LongIntensity"
            return 1
        else:
            return 0
    if theoreticalWorkout["workoutType"] == "ShortIntensity":
        if (
            actualWorkout["secondsInZone"][5]
            * 3600
            * TSS_BY_ZONE_BY_SPORT[actualWorkout["activity"]][5]
            + actualWorkout["secondsInZone"][6]
            * 3600
            * TSS_BY_ZONE_BY_SPORT[actualWorkout["activity"]][6]
            + actualWorkout["secondsInZone"][7]
            * 3600
            * TSS_BY_ZONE_BY_SPORT[actualWorkout["activity"]][7]
            > theoreticalWorkout["tss"] * 0.8
        ):
            actualWorkout["workoutType"] = "ShortIntensity"
            return 1
        else:
            return 0
    if "tss" in actualWorkout:
        if actualWorkout["tss"] > theoreticalWorkout["tss"] * 0.8:
            return 1
        else:
            return 0


def analyzeMicrocycle(microcycle, completedWorkouts, raceZone, mainSport):
    actualWeekWorkouts = [
        workout
        for workout in completedWorkouts
        if workout["date"] >= microcycle["startDate"]
        and workout["date"] <= microcycle["endDate"]
    ]
    totalTSS = sum([workout.get("tss", 0) for workout in actualWeekWorkouts])
    microcycle["actualTSS"] = totalTSS

    # to a time repartition tss aggregation
    actualSecondsInZone = {zone: 0 for zone in ZONES[mainSport].keys()}
    for workout in actualWeekWorkouts:
        for zone, tss in workout["secondsInZone"].items():
            actualSecondsInZone[zone] += workout["secondsInZone"][zone]
    microcycle["actualSecondsInZone"] = actualSecondsInZone

    theroeticalTimeSpentWeekInSeconds = (
        microcycle["theoreticalWeeklyTSS"]
        * 3600
        / sum(
            [
                TSS_BY_ZONE_BY_SPORT[mainSport][zone]
                * microcycle["timeInZoneRepartition"][zone]
                for zone in ZONES[mainSport].keys()
            ]
        )
    )
    microcycle["theoreticalTimeSpentWeek"] = timedelta(
        seconds=theroeticalTimeSpentWeekInSeconds
    )

    theoreticalTimeInZone = {
        zone: microcycle["timeInZoneRepartition"][zone]
        * theroeticalTimeSpentWeekInSeconds
        for zone in ZONES[mainSport].keys()
    }
    microcycle["theoreticalTimeInZone"] = theoreticalTimeInZone

    microcycle["deltaTimeInZone"] = {
        zone: microcycle["actualSecondsInZone"][zone] - theoreticalTimeInZone[zone]
        for zone in ZONES[mainSport].keys()
    }

    maxTSSWorkout = 0
    # Check if the theoreticalLongWorkoutTSS was respected
    microcycle["longWorkoutDone"] = False
    for workout in actualWeekWorkouts:
        if workout.get("tss", 0) > maxTSSWorkout:
            maxTSSWorkout = workout.get("tss", 0)
        if workout.get("tss", 0) > microcycle["theoreticalLongWorkoutTSS"] * 0.85:
            microcycle["longWorkoutDone"] = True
            break
    microcycle["actualLongWorkoutTSS"] = maxTSSWorkout

    # Check if the theoreticalRaceIntensityTSS was respected
    maxRaceIntensityTSS = 0
    microcycle["RaceIntensityDone"] = False
    for workout in actualWeekWorkouts:
        if (
            raceZone in workout["secondsInZone"]
            and workout["secondsInZone"][raceZone] > maxRaceIntensityTSS
        ):
            maxRaceIntensityTSS = (
                workout["secondsInZone"][raceZone]
                * TSS_BY_ZONE_BY_SPORT[mainSport][raceZone]
                / 3600
            )
            if maxRaceIntensityTSS > microcycle["theoreticalRaceIntensityTSS"] * 0.85:
                microcycle["RaceIntensityDone"] = True
                break
    microcycle["actualRaceIntensityTSS"] = maxRaceIntensityTSS

    # Check if the long intensity workout was respected
    maxLongIntensityTSS = 0
    microcycle["LongIntensityDone"] = False
    for workout in actualWeekWorkouts:
        if (
            4 in workout["secondsInZone"] and 3 in workout["secondsInZone"]
        ) and workout["secondsInZone"][4] + workout["secondsInZone"][
            3
        ] > maxLongIntensityTSS:
            maxLongIntensityTSS = (
                workout["secondsInZone"][4] * TSS_BY_ZONE_BY_SPORT[mainSport][4]
                + workout["secondsInZone"][3] * TSS_BY_ZONE_BY_SPORT[mainSport][3]
            ) / 60
            if maxLongIntensityTSS > microcycle["theoreticalLongIntensityTSS"] * 0.85:
                microcycle["LongIntensityDone"] = True
                break
    microcycle["actualLongIntensityTSS"] = maxLongIntensityTSS

    # Check if the short intensity workout was respected
    maxShortIntensityTSS = 0
    microcycle["ShortIntensityDone"] = False
    for workout in actualWeekWorkouts:
        if (
            5 in workout["secondsInZone"]
            and 6 in workout["secondsInZone"]
            and 7 in workout["secondsInZone"]
        ) and workout["secondsInZone"][5] + workout["secondsInZone"][6] + workout[
            "secondsInZone"
        ][7] > maxShortIntensityTSS:
            maxShortIntensityTSS = (
                workout["secondsInZone"][5] * TSS_BY_ZONE_BY_SPORT[mainSport][5]
                + workout["secondsInZone"][6] * TSS_BY_ZONE_BY_SPORT[mainSport][6]
                + workout["secondsInZone"][7] * TSS_BY_ZONE_BY_SPORT[mainSport][7]
            ) / 60
            if maxShortIntensityTSS > microcycle["theoreticalShortIntensityTSS"] * 0.85:
                microcycle["ShortIntensityDone"] = True
                break
    microcycle["actualShortIntensityTSS"] = maxShortIntensityTSS

    # Check if it is a rest week

    if microcycle["theoreticalResting"]:
        if totalTSS <= microcycle["theoreticalWeeklyTSS"] * 1.2:
            microcycle["actualResting"] = True
        else:
            microcycle["actualResting"] = False
            microcycle["nextWeekGuidelines"] = "Rest"
    else:
        if totalTSS <= microcycle["theoreticalWeeklyTSS"] * 0.6:
            microcycle["actualResting"] = True
            microcycle["nextWeekGuidelines"] = "Normal"
        else:
            microcycle["actualResting"] = False

    missingKeyWorkouts = []
    missingKeyWorkoutsPlanned = []
    for workout in microcycle["keyWorkouts"]:
        # Find the theoretical workout in the microcycle dayByDay
        theoreticalWorkout = None
        for day in microcycle["dayByDay"]:
            for plannedWorkout in microcycle["dayByDay"][day]:
                if plannedWorkout["workoutType"] == workout:
                    theoreticalWorkout = plannedWorkout
                    break
        if theoreticalWorkout is None:
            missingKeyWorkoutsPlanned.append(workout)

        done = False
        if theoreticalWorkout is not None:
            for actualWorkout in actualWeekWorkouts:
                if checkWorkoutValidity(actualWorkout, theoreticalWorkout) > 0.8:
                    done = True
                    break
        if not done:
            missingKeyWorkouts.append(workout)
    microcycle["missingKeyWorkouts"] = missingKeyWorkouts

    microcycle["analyzed"] = True


def planWeekLoads(
    loadsInfo,
    datesInfo,
    raceInfo,
    weekInfo,
    currentPlannedMacrocycles,
    currentPlannedMicrocycles,
    completedWorkouts,
    race_number
):
    log_debug(f"Planning week with loadsInfo: {loadsInfo}, datesInfo: {datesInfo}, raceInfo: {raceInfo}, weekInfo: {weekInfo}, currentPlannedMacrocycles: {currentPlannedMacrocycles}, currentPlannedMicrocycles: {currentPlannedMicrocycles}, completedWorkouts: {completedWorkouts}")

    totalMacrocycles = currentPlannedMacrocycles.copy()
    totalMicrocycles = currentPlannedMicrocycles.copy()

    pastMacrocycles = [
        macrocycle
        for macrocycle in totalMacrocycles
        if macrocycle["endDate"] < datesInfo["currentDate"]
    ]
    pastMicrocycles = [
        microcycle
        for microcycle in totalMicrocycles
        if microcycle["endDate"] < datesInfo["currentDate"]
    ]

    currentMacrocycle = {}
    for i, macrocycle in enumerate(totalMacrocycles):
        if (
            macrocycle["endDate"] >= datesInfo["currentDate"]
            and macrocycle["startDate"] <= datesInfo["currentDate"]
        ):
            currentMacrocycle = totalMacrocycles[i]
            break
    currentMicrocycle = {}
    for i, microcycle in enumerate(totalMicrocycles):
        if (
            microcycle["endDate"] >= datesInfo["currentDate"]
            and microcycle["startDate"] <= datesInfo["currentDate"]
        ):
            currentMicrocycle = totalMicrocycles[i]
            break

    futureMacrocycles = [
        macrocycle
        for macrocycle in totalMacrocycles
        if macrocycle["startDate"] > datesInfo["currentDate"]
    ]
    futureMicrocycles = [
        microcycle
        for microcycle in totalMicrocycles
        if microcycle["startDate"] > datesInfo["currentDate"]
    ]

    # Check if the past was analyzed, if not analyze it
    if pastMacrocycles:
        for macrocycle in pastMacrocycles:
            if "analyzed" not in macrocycle or not macrocycle["analyzed"]:
                analyzeMacrocycle(
                    macrocycle,
                    completedWorkouts,
                    raceInfo["raceZone"],
                    raceInfo["mainSport"],
                )
                macrocycle["analyzed"] = True
    if pastMicrocycles:
        for microcycle in pastMicrocycles:
            if "analyzed" not in microcycle or not microcycle["analyzed"]:
                analyzeMicrocycle(
                    microcycle,
                    completedWorkouts,
                    raceInfo["raceZone"],
                    raceInfo["mainSport"],
                )

    # First compare what was completed to what was planned
    lastWeeksTakeaways = currentLoadStatus(pastMicrocycles)
    if "declaredHandableLoad" in loadsInfo:
        # startLoad = loadsInfo["declaredHandableLoad"]
        startLoad = loadsInfo["startLoad"]
    else:
        startLoad = lastWeeksTakeaways["currentHandableLoad"]
    # Compare this with the current microcycle, are we corresponding to the plan?

    if "nextRestingWeek" in loadsInfo and loadsInfo["nextRestingWeek"] is not None:
        nextRestingWeek = loadsInfo["nextRestingWeek"]
    else:
        nextRestingWeek = (
            lastWeeksTakeaways["nextRestingWeek"] - 1
            if lastWeeksTakeaways["nextRestingWeek"] > 0
            else 0
        )

    if currentMicrocycle != {}:
        compareCurrentWeekWithPlannedWeekAndReplanIfNeeded(
            completedWorkouts=completedWorkouts,
            currentMicrocycle=currentMicrocycle,
            startLoad=startLoad,
            currentDay=datesInfo["currentDate"].weekday(),
            lastWeeksTakeaways=lastWeeksTakeaways,
            maxTssPerDay=loadsInfo["maxTssPerDay"],
            mainSport=raceInfo["mainSport"],
        )

    nextRestingWeek = nextRestingWeek - 1 if nextRestingWeek > 0 else 0
    if currentMicrocycle.get("actualResting", None) or currentMicrocycle.get(
        "theoreticalResting", None
    ):
        nextRestingWeek = loadsInfo["cycleLength"]

    # Compute what would be the ideal fondamental weeks
    fondamentalWeeks, nextRestingWeek, lastCycleNumber = (
        computeFondamentalWeeksRequired(
            startLoad * (1 + loadsInfo["weeklyTssIncreaseRate"]),
            currentMicrocycle.get("cycleNumber", 1),
            currentMicrocycle.get("indexInCycle", 0),
            loadsInfo["endLoad"],
            loadsInfo["weeklyTssIncreaseRate"],
            loadsInfo["cycleLength"],
            nextRestingWeek,
            lastWeeksTakeaways,
        )
    )
    numberOfFondamentalWeeks = len(fondamentalWeeks)

    log_debug("Fondamental weeks computed")
    log_debug(fondamentalWeeks)

    # Let's compute what should be the next week macrocycle
    currentStep = CYCLE_TYPES[-1]
    currentPlanningDate = datesInfo["endDate"]

    dateOfStartPreComp = (
        datesInfo["endDate"]
        - timedelta(
            days=MAX_CYCLES_TIMING_DAYS_TO_RACE_BY_OBJECTIVE_BY_OBJECTIVE_SIZE[
                raceInfo["objective"]
            ][raceInfo["eventSize"]]["Pre-Compet"]
        )
        - timedelta(
            days=MAX_CYCLES_TIMING_DAYS_TO_RACE_BY_OBJECTIVE_BY_OBJECTIVE_SIZE[
                raceInfo["objective"]
            ][raceInfo["eventSize"]]["Compet"]
        )
        + timedelta(days=1)
    )
    
    
    daysAhead = 7 - datesInfo["currentDate"].weekday() % 7
    if daysAhead == 0:
        daysAhead = 7
    nextMondayDate = final_date(datesInfo["currentDate"] + timedelta(days=(daysAhead)))

    mondayBeginningOfPreComp = final_date(dateOfStartPreComp - timedelta(
        days=dateOfStartPreComp.weekday()
    ))
    numberOfWeeksAvailableFondSpe =round((
        mondayBeginningOfPreComp
        - nextMondayDate
    ).days / 7) # begins after the current week
    if currentMicrocycle == {} and race_number != 0 and datesInfo["currentDate"].weekday() < 6:
        numberOfWeeksAvailableFondSpe += 1
    if dateOfStartPreComp.weekday() != 0:
        numberOfWeeksAvailableFondSpe += 1
    log_info(
        f"next monday date: {nextMondayDate} Date of start precomp: {dateOfStartPreComp}, monday before precomp: {mondayBeginningOfPreComp}, number of weeks available fond spe: {numberOfWeeksAvailableFondSpe}, current microcycle: {currentMicrocycle}, race number: {race_number}, date of start precomp weekday: {dateOfStartPreComp.weekday()}, current date {datesInfo['currentDate']}, number of days: {(dateOfStartPreComp - date(datesInfo['currentDate'].year, datesInfo['currentDate'].month, datesInfo['currentDate'].day)).days}"
    )

    specificWeeks = []

    if numberOfFondamentalWeeks > numberOfWeeksAvailableFondSpe:
        fondamentalWeeks = fondamentalWeeks[:numberOfWeeksAvailableFondSpe]
        # if last week is rest, change it to a normal week
        lastRestingWeekIndex = 0
        for i in range(len(fondamentalWeeks)):
            if fondamentalWeeks[i].get("actualResting", None) or fondamentalWeeks[
                i
            ].get("theoreticalResting", None):
                lastRestingWeekIndex = i

        nextRestingWeek = len(fondamentalWeeks) - lastRestingWeekIndex - 2
        if len(fondamentalWeeks) > 1:
            currentCycleNumber = (
                fondamentalWeeks[-1]["cycleNumber"] + 1
                if fondamentalWeeks[-1]["indexInCycle"] == loadsInfo["cycleLength"] - 1
                else fondamentalWeeks[-1]["cycleNumber"]
            )
            currentIndexInCycle = (
                fondamentalWeeks[-1]["indexInCycle"] + 1
                if fondamentalWeeks[-1]["indexInCycle"] < loadsInfo["cycleLength"] - 1
                else 1
            )
        else:
            currentCycleNumber = 1
            currentIndexInCycle = 1
    else:
        number_of_specific_weeks = (
            numberOfWeeksAvailableFondSpe - numberOfFondamentalWeeks
        )
        currentCycleNumber = (
            fondamentalWeeks[-1]["cycleNumber"] + 1
            if fondamentalWeeks[-1]["indexInCycle"] == loadsInfo["cycleLength"] - 1
            else fondamentalWeeks[-1]["cycleNumber"]
        )
        currentIndexInCycle = (
            fondamentalWeeks[-1]["indexInCycle"] + 1
            if fondamentalWeeks[-1]["indexInCycle"] < loadsInfo["cycleLength"] - 1
            else 1
        )
        lastRestingWeekIndex = 0
        for i in range(len(fondamentalWeeks)):
            if fondamentalWeeks[i].get("actualResting", None) or fondamentalWeeks[
                i
            ].get("theoreticalResting", None):
                lastRestingWeekIndex = i
        nextRestingWeek = len(fondamentalWeeks) - lastRestingWeekIndex - 2
        specificWeeks = getSpecificWeeks(
            number_of_specific_weeks,
            loadsInfo["endLoad"],
            loadsInfo["cycleLength"],
            nextRestingWeek,
            currentCycleNumber + 1,
            currentIndexInCycle,
        )
        
    log_info(f"number of fondamentalWeeks: {len(fondamentalWeeks)}, number of specific weeks: {len(specificWeeks)}")

    planBeforePreComp = fondamentalWeeks + specificWeeks

    # Add the key workouts formats:
    currentHandableBiggestWorkout = lastWeeksTakeaways.get(
        "biggestWorkout", loadsInfo["currentLongRunTSS"]
    ) * (1 + loadsInfo["weeklyTssIncreaseRate"])
    currentHandableShortIntensity = lastWeeksTakeaways.get(
        "currentShortIntensity", 10
    ) * (1 + loadsInfo["weeklyTssIncreaseRate"])
    currentHandableRaceIntensity = lastWeeksTakeaways.get(
        "currentRaceIntensity", 15
    ) * (1 + loadsInfo["weeklyTssIncreaseRate"])
    currentHandableLongIntensity = lastWeeksTakeaways.get(
        "currentLongIntensity", 15
    ) * (1 + loadsInfo["weeklyTssIncreaseRate"])

    if loadsInfo.get("currentLongRunTSS", None) is not None:
        currentHandableBiggestWorkout = loadsInfo["currentLongRunTSS"]
    if loadsInfo.get("currentShortIntensityTSS", None) is not None:
        currentHandableShortIntensity = loadsInfo["currentShortIntensityTSS"]
    if loadsInfo.get("currentRaceIntensityTSS", None) is not None:
        currentHandableRaceIntensity = loadsInfo["currentRaceIntensityTSS"]
    if loadsInfo.get("currentLongIntensityTSS", None) is not None:
        currentHandableLongIntensity = loadsInfo["currentLongIntensityTSS"]

    for i, week in enumerate(planBeforePreComp):
        ratio = 1
        if week["theoreticalResting"]:
            ratio = 0.7
        if "Long" in week.get("keyWorkouts", []):
            week["theoreticalLongWorkoutTSS"] = currentHandableBiggestWorkout * ratio
            number_of_future_weeks_having_long_in_key_workouts = 0
            for future_week in planBeforePreComp[i + 1 :]:
                if "Long" in future_week.get("keyWorkouts", []):
                    number_of_future_weeks_having_long_in_key_workouts += 1

            currentHandableBiggestWorkout += (
                loadsInfo.get("finalLongRunTSS", loadsInfo["maxTssPerWorkout"])
                - currentHandableBiggestWorkout
            ) / (number_of_future_weeks_having_long_in_key_workouts + 1)

        if "ShortIntensity" in week.get("keyWorkouts", []):
            week["theoreticalShortIntensityTSS"] = currentHandableShortIntensity * ratio
            number_of_future_weeks_having_short_in_key_workouts = 0
            for future_week in planBeforePreComp[i + 1 :]:
                if "ShortIntensity" in future_week.get("keyWorkouts", []):
                    number_of_future_weeks_having_short_in_key_workouts += 1

            currentHandableShortIntensity += (
                loadsInfo.get("finalShortIntensityTSS", loadsInfo["maxTssPerWorkout"])
                - currentHandableShortIntensity
            ) / (number_of_future_weeks_having_short_in_key_workouts + 1)

        if "theoreticalRaceIntensityTSS" in week.get("keyWorkouts", []):
            week["theoreticalRaceIntensityTSS"] = currentHandableRaceIntensity * ratio
            number_of_future_week_having_race_in_key_workouts = 0
            for future_week in planBeforePreComp[i + 1 :]:
                if "RaceIntensity" in future_week.get("keyWorkouts", []):
                    number_of_future_week_having_race_in_key_workouts += 1
            currentHandableRaceIntensity += (
                loadsInfo.get("finalRaceIntensityTSS", loadsInfo["maxTssPerWorkout"])
                - currentHandableRaceIntensity
            ) / (number_of_future_week_having_race_in_key_workouts + 1)

        if "LongIntensity" in week.get("keyWorkouts", []):
            week["theoreticalLongIntensityTSS"] = currentHandableLongIntensity * ratio
            number_of_future_week_having_long_intensity_in_key_workouts = 0
            for future_week in planBeforePreComp[i + 1 :]:
                if "LongIntensity" in future_week.get("keyWorkouts", []):
                    number_of_future_week_having_long_intensity_in_key_workouts += 1
            currentHandableLongIntensity += (
                loadsInfo.get("finalLongIntensityTSS", loadsInfo["maxTssPerWorkout"])
                - currentHandableLongIntensity
            ) / (number_of_future_week_having_long_intensity_in_key_workouts + 1)

    log_debug("Current Step before checking competition cycle")
    log_debug(currentStep)
    if currentStep == "Compet":  # Edit or Create the competition cycle
        # Try to find the competition cycle
        found = False
        for i, macrocycle in enumerate(totalMacrocycles):
            if macrocycle["cycleType"] == "Compet":
                found = True
                competitionMacrocycle = update_macrocycle(
                    macrocycle,
                    {
                        "endDate": datesInfo["endDate"],
                        "startDate": max(final_date(datesInfo["endDate"]
                        - timedelta(
                            days=MAX_CYCLES_TIMING_DAYS_TO_RACE_BY_OBJECTIVE_BY_OBJECTIVE_SIZE[
                                raceInfo["objective"]
                            ][raceInfo["eventSize"]]["Compet"]
                        ) + timedelta(days=1)), final_date(datesInfo["currentDate"])),
                        "totalTSS": raceInfo["eventTSS"]
                        * COMPET_CYCLE_TSS_MULTIPLICATOR_BY_SPORT_BY_OBJECTIVE_OBJECTIVE_SIZE[
                            raceInfo["mainSport"]
                        ][raceInfo["objective"]][raceInfo["eventSize"]],
                    },
                )
        # if not present, create it
        if not found:
            log_debug("Creating competition macrocycle")
            competitionMacrocycle = {
                "cycleType": "Compet",
                "startDate": max(final_date(datesInfo["endDate"]
                - timedelta(
                    days=MAX_CYCLES_TIMING_DAYS_TO_RACE_BY_OBJECTIVE_BY_OBJECTIVE_SIZE[
                        raceInfo["objective"]
                    ][raceInfo["eventSize"]]["Compet"]
                ) + timedelta(days=1)), final_date(datesInfo["currentDate"])),
                "endDate": datesInfo["endDate"],
                "totalTSS": raceInfo["eventTSS"]
                * COMPET_CYCLE_TSS_MULTIPLICATOR_BY_SPORT_BY_OBJECTIVE_OBJECTIVE_SIZE[
                    raceInfo["mainSport"]
                ][raceInfo["objective"]][raceInfo["eventSize"]],
            }

        # Do the same with the microcycle
        found = False
        for i, microcycle in enumerate(totalMicrocycles):
            if microcycle["cycleType"] == "Compet":
                found = True
                competitionMicrocycle = update_microcycle(
                    microcycle,
                    {
                        "endDate": datesInfo["endDate"],
                        "startDate": max(final_date(datesInfo["endDate"]
                        - timedelta(
                            days=MAX_CYCLES_TIMING_DAYS_TO_RACE_BY_OBJECTIVE_BY_OBJECTIVE_SIZE[
                                raceInfo["objective"]
                            ][raceInfo["eventSize"]]["Compet"]
                        ) + timedelta(days=1)), final_date(datesInfo["currentDate"])),
                        "theoreticalWeeklyTSS": raceInfo["eventTSS"]
                        * COMPET_CYCLE_TSS_MULTIPLICATOR_BY_SPORT_BY_OBJECTIVE_OBJECTIVE_SIZE[
                            raceInfo["mainSport"]
                        ][raceInfo["objective"]][raceInfo["eventSize"]],
                    },
                )
                currentPlanningDate = competitionMicrocycle["startDate"]
        if not found:
            log_debug("Creating competition microcycle")
            competitionMicrocycle = {
                "cycleType": "Compet",
                "startDate": max(final_date(datesInfo["endDate"]
                - timedelta(
                    days=MAX_CYCLES_TIMING_DAYS_TO_RACE_BY_OBJECTIVE_BY_OBJECTIVE_SIZE[
                        raceInfo["objective"]
                    ][raceInfo["eventSize"]]["Compet"]
                ) + timedelta(days=1)), final_date(datesInfo["currentDate"])),
                "endDate": datesInfo["endDate"],
                "theoreticalWeeklyTSS": raceInfo["eventTSS"]
                * COMPET_CYCLE_TSS_MULTIPLICATOR_BY_SPORT_BY_OBJECTIVE_OBJECTIVE_SIZE[
                    raceInfo["mainSport"]
                ][raceInfo["objective"]][raceInfo["eventSize"]],
            }
            currentPlanningDate = competitionMicrocycle["startDate"]
        log_info("Current planning date")
        log_info(currentPlanningDate)
        log_info(datesInfo["currentDate"])
        if datesInfo["currentDate"] >= datetime(
            currentPlanningDate.year, currentPlanningDate.month, currentPlanningDate.day
        ):
            # We are in the competition cycle
            log_info("We are in the competition cycle")
            planAnotherWeek = False
        else:
            log_info("We are before the competition cycle")
            currentStep = "Pre-Compet"
    precompetMicrocycle = {}
    precompetMacrocycle = {}
    if currentStep == "Pre-Compet":
        found = False
        for i, macrocycle in enumerate(totalMacrocycles):
            if macrocycle["cycleType"] == "Pre-Compet":
                found = True
                log_debug("Updating precompet macrocycle")
                precompetMacrocycle = update_macrocycle(
                    macrocycle,
                    {
                        "endDate": competitionMacrocycle["startDate"]
                        - timedelta(days=1),
                        "startDate": max(final_date(competitionMacrocycle["startDate"]
                        - timedelta(
                            days=MAX_CYCLES_TIMING_DAYS_TO_RACE_BY_OBJECTIVE_BY_OBJECTIVE_SIZE[
                                raceInfo["objective"]
                            ][raceInfo["eventSize"]]["Pre-Compet"]
                        )), final_date(datesInfo["currentDate"])),
                        "totalTSS": loadsInfo["endLoad"]
                        / 2
                        * ((competitionMacrocycle["startDate"] - timedelta(days=1)-max(final_date(competitionMacrocycle["startDate"]
                            - timedelta(
                                days=MAX_CYCLES_TIMING_DAYS_TO_RACE_BY_OBJECTIVE_BY_OBJECTIVE_SIZE[
                                    raceInfo["objective"]
                                ][raceInfo["eventSize"]]["Pre-Compet"]
                            )), final_date(datesInfo["currentDate"]))).days + 1)
                        / 7,
                        "theoreticalResting": True,
                    },
                )
        if not found:
            log_debug("Creating precompet macrocycle")
            precompetMacrocycle = {
                "cycleType": "Pre-Compet",
                "startDate": max(final_date(competitionMacrocycle["startDate"]
                - timedelta(
                    days=MAX_CYCLES_TIMING_DAYS_TO_RACE_BY_OBJECTIVE_BY_OBJECTIVE_SIZE[
                        raceInfo["objective"]
                    ][raceInfo["eventSize"]]["Pre-Compet"]
                )), final_date(datesInfo["currentDate"])),
                "endDate": competitionMacrocycle["startDate"] - timedelta(days=1),
                "theoreticalWeeklyTSS": loadsInfo["endLoad"]
                / 2
                * ((competitionMacrocycle["startDate"] - timedelta(days=1)-max(final_date(competitionMacrocycle["startDate"]
                - timedelta(
                    days=MAX_CYCLES_TIMING_DAYS_TO_RACE_BY_OBJECTIVE_BY_OBJECTIVE_SIZE[
                        raceInfo["objective"]
                    ][raceInfo["eventSize"]]["Pre-Compet"]
                )), final_date(datesInfo["currentDate"]))).days + 1)
                / 7,
                "theoreticalResting": True,
            }
        found = False
        for i, microcycle in enumerate(totalMicrocycles):
            if microcycle["cycleType"] == "Pre-Compet":
                log_debug("Updating precompet microcycle")
                found = True
                precompetMicrocycle = update_microcycle(
                    microcycle,
                    {
                        "endDate": competitionMicrocycle["startDate"]
                        - timedelta(days=1),
                        "startDate": max(final_date(competitionMicrocycle["startDate"]
                        - timedelta(
                            days=MAX_CYCLES_TIMING_DAYS_TO_RACE_BY_OBJECTIVE_BY_OBJECTIVE_SIZE[
                                raceInfo["objective"]
                            ][raceInfo["eventSize"]]["Pre-Compet"]
                        )), final_date(datesInfo["currentDate"])),
                        "theoreticalWeeklyTSS": loadsInfo["endLoad"]
                        / 2
                        * ((competitionMacrocycle["startDate"] - timedelta(days=1)-max(final_date(competitionMacrocycle["startDate"]
                            - timedelta(
                                days=MAX_CYCLES_TIMING_DAYS_TO_RACE_BY_OBJECTIVE_BY_OBJECTIVE_SIZE[
                                    raceInfo["objective"]
                                ][raceInfo["eventSize"]]["Pre-Compet"]
                            )), final_date(datesInfo["currentDate"]))).days + 1)
                        / 7,
                        "theoreticalResting": True,
                    },
                )
                currentPlanningDate = precompetMicrocycle["startDate"]
        if not found:
            log_debug("Creating precompet microcycle")
            precompetMicrocycle = {
                "cycleType": "Pre-Compet",
                "startDate": max(final_date(competitionMicrocycle["startDate"]
                - timedelta(
                    days=MAX_CYCLES_TIMING_DAYS_TO_RACE_BY_OBJECTIVE_BY_OBJECTIVE_SIZE[
                        raceInfo["objective"]
                    ][raceInfo["eventSize"]]["Pre-Compet"]
                )), final_date(datesInfo["currentDate"])),
                "endDate": competitionMicrocycle["startDate"] - timedelta(days=1),
                "theoreticalWeeklyTSS": loadsInfo["endLoad"]
                / 2
                * ((competitionMacrocycle["startDate"] - timedelta(days=1)-max(final_date(competitionMacrocycle["startDate"]
                - timedelta(
                    days=MAX_CYCLES_TIMING_DAYS_TO_RACE_BY_OBJECTIVE_BY_OBJECTIVE_SIZE[
                        raceInfo["objective"]
                    ][raceInfo["eventSize"]]["Pre-Compet"]
                )), final_date(datesInfo["currentDate"]))).days + 1)
                / 7,
                "theoreticalResting": True,
            }
            currentPlanningDate = precompetMicrocycle["startDate"]
        log_debug(f"Current planning date {currentPlanningDate}. Current date {datesInfo['currentDate']}")

        if datesInfo["currentDate"] >= datetime(
            currentPlanningDate.year, currentPlanningDate.month, currentPlanningDate.day
        ):
            # We are in the precompet cycle
            log_debug("We are in the precompet cycle")
            planAnotherWeek = False
        else:
            log_debug("We are before the precompet cycle")
            currentStep = "Before Pre Comp"
    
    newPlanBeforePreComp = []
    
    if currentStep == "Before Pre Comp":
        # We begin next monday after current date

        if currentMicrocycle == {} and race_number == 0:
            # Add a currentMicrocycle
            currentMicrocycleBeforePreComp = {
                "cycleType": "Fondamental",
                "startDate": datesInfo["currentDate"],
                "endDate": datesInfo["currentDate"]+timedelta(days=6-datesInfo["currentDate"].weekday()),
                "theoreticalWeeklyTSS": startLoad*((6-datesInfo["currentDate"].weekday())/7) if loadsInfo.get("nextRestingWeek", 4) >=1  else startLoad*((6-datesInfo["currentDate"].weekday())/7/2),
                "theoreticalResting": loadsInfo.get("nextRestingWeek", 4) <1,
                "keyWorkouts": [],
                "dayByDay": {},
            }
            log_debug(f"Creating current microcycle {currentMicrocycleBeforePreComp}")
            newPlanBeforePreComp.append(currentMicrocycleBeforePreComp)
        
        
        beginningOfNextWeek = (
            datesInfo["currentDate"]
            + timedelta(days=(7 - datesInfo["currentDate"].weekday()))
        )
        # Remove comp and precomp from the futureMicrocycles
        futureMicrocycles = [
            microcycle
            for microcycle in futureMicrocycles
            if microcycle["cycleType"] not in ["Pre-Compet", "Compet"]
        ]
        # order them by date
        futureMicrocycles = sorted(futureMicrocycles, key=lambda x: x["startDate"])
        # Compare week after week the planBeforePreComp with the futureMicrocycles (except precomp and comp) and update if needed
        
        for i, newMicrocycle in enumerate(planBeforePreComp):
            # Try get matching microcycle
            currentPlanningDate = beginningOfNextWeek + timedelta(days=7 * i)
            if i < len(futureMicrocycles):
                oldMicrocycle = futureMicrocycles[i]
                endDate = currentPlanningDate + timedelta(days=6)
                theoreticalWeeklyTSS = newMicrocycle["theoreticalWeeklyTSS"]
                keyWorkouts = newMicrocycle.get("keyWorkouts", [])
                # if we are the last week of the planBeforePreComp, we have to adapt the date of the end to a day before the beginning of pre compet
                if i == len(planBeforePreComp) - 1:
                    endDate = precompetMicrocycle["startDate"] - timedelta(days=1)
                    theoreticalWeeklyTSS = (
                        theoreticalWeeklyTSS * (endDate.weekday() + 1) / 7
                    )
                    if endDate.weekday() <= 3:
                        if "Long" in keyWorkouts:
                            keyWorkouts.remove("Long")
                newMicrocycle = update_microcycle(
                    oldMicrocycle,
                    {
                        "startDate": currentPlanningDate,
                        "endDate": endDate,
                        "theoreticalWeeklyTSS": theoreticalWeeklyTSS,
                        "theoreticalResting": newMicrocycle["theoreticalResting"],
                        "keyWorkouts": keyWorkouts,
                        "theoreticalLongWorkoutTSS": newMicrocycle.get(
                            "theoreticalLongWorkoutTSS", 0
                        ),
                    },
                )
                log_debug(
                    f"Updating microcycle {newMicrocycle}, currentPlanningDate: {currentPlanningDate}"
                )
            else:
                newMicrocycle["startDate"] = currentPlanningDate
                newMicrocycle["endDate"] = currentPlanningDate + timedelta(days=6)
                log_debug(
                    f"Creating microcycle {newMicrocycle}, currentPlanningDate: {currentPlanningDate}"
                )
                if i == len(planBeforePreComp) - 1:
                    newMicrocycle["endDate"] = precompetMicrocycle[
                        "startDate"
                    ] - timedelta(days=1)
                    newMicrocycle["theoreticalWeeklyTSS"] = (
                        newMicrocycle["theoreticalWeeklyTSS"]
                        * (newMicrocycle["endDate"].weekday() + 1)
                        / 7
                    )
                    if newMicrocycle["endDate"].weekday() <= 3:
                        if "Long" in newMicrocycle.get("keyWorkouts", []):
                            newMicrocycle["keyWorkouts"].remove("Long")
            newPlanBeforePreComp.append(newMicrocycle)

    totalMacrocycles = (
        pastMacrocycles
        + [currentMacrocycle]
        + futureMacrocycles
        + [precompetMacrocycle]
        + [competitionMacrocycle]
    )
    log_info(f"pastMicrocycles: {pastMicrocycles}, currentMicrocycle: {currentMicrocycle}, newPlanBeforePreComp: {newPlanBeforePreComp}, precompetMicrocycle: {precompetMicrocycle}, competitionMicrocycle: {competitionMicrocycle}")
    for microcycle in newPlanBeforePreComp:
        if microcycle != {}:
            microcycle = planFutureWeekDayByDay(microcycle, weekInfo, raceInfo, loadsInfo, datesInfo)
    if precompetMicrocycle != {}:
        precompetMicrocycle = planFutureWeekDayByDay(precompetMicrocycle, weekInfo, raceInfo, loadsInfo, datesInfo)
    if competitionMicrocycle != {}:
        competitionMicrocycle = planFutureWeekDayByDay(competitionMicrocycle, weekInfo, raceInfo, loadsInfo, datesInfo)
    log_debug(f"competitionMicrocycle: {competitionMicrocycle}")
    log_debug(f"pastMicrocycles: {pastMicrocycles}, currentMicrocycle: {currentMicrocycle}, newPlanBeforePreComp: {newPlanBeforePreComp}, precompetMicrocycle: {precompetMicrocycle}, competitionMicrocycle: {competitionMicrocycle}")
    totalMicrocycles = pastMicrocycles

    # Add currentMicrocycle if it's not empty
    if currentMicrocycle != {}:
        totalMicrocycles.append(currentMicrocycle)

    # Add all non-empty items in the correct order
    totalMicrocycles.extend(newPlanBeforePreComp)

    if precompetMicrocycle != {}:
        totalMicrocycles.append(precompetMicrocycle)

    if competitionMicrocycle != {}:
        totalMicrocycles.append(competitionMicrocycle)

    
    log_debug(f"Total microcycles: {totalMicrocycles}")

    return totalMacrocycles, totalMicrocycles


def planFutureWeekDayByDay(futureMicrocycle, weekInfo, raceInfo, loadsInfo, datesInfo):
    log_info(f"Planning future week day by day for {futureMicrocycle}")

    remaining_tss = futureMicrocycle["theoreticalWeeklyTSS"]
    availableDays = weekInfo["availableDays"].copy()
    dayAvailableDurations = weekInfo["dayAvailableDurations"].copy()

    futureMicrocycle["timeInZoneRepartition"] = (
        ZONE_REPARTITION_BY_TIME_BY_WEEK_BY_CYCLE[
            raceInfo["fitnessLevel"]
        ][futureMicrocycle["cycleType"]][raceInfo["eventSize"]]
    )
    theroeticalTimeSpentWeekInSeconds = (
        futureMicrocycle["theoreticalWeeklyTSS"]
        * 3600
        / sum(
            [
                TSS_BY_ZONE_BY_SPORT[raceInfo["mainSport"]][zone]
                * futureMicrocycle["timeInZoneRepartition"][zone]
                for zone in ZONES[raceInfo["mainSport"]].keys()
            ]
        )
    )
    theoreticalTimeInZone = {
        zone: futureMicrocycle["timeInZoneRepartition"][zone]
        * theroeticalTimeSpentWeekInSeconds
        for zone in ZONES[raceInfo["mainSport"]].keys()
    }
    log_debug(f"Theoretical time in zone {theoreticalTimeInZone}")

    dayByDay = {}
    if "compet" == futureMicrocycle["cycleType"].lower():
        # Let's plan the competition
        log_info("Planning competition")
        # Let's plan the competition
        competitionTSS = raceInfo["eventTSS"]
        targetTimeInSeconds = raceInfo["targetTimeInMinutes"] * 60
        competitionZone = raceInfo["raceZone"]
        weekDaysMapping = ("Monday", "Tuesday", 
                   "Wednesday", "Thursday",
                   "Friday", "Saturday",
                   "Sunday")
        
        dayByDay[weekDaysMapping[futureMicrocycle["endDate"].weekday()]] = [{
            "workoutType": "Competition",
            "activity": raceInfo["mainSport"],
            "tss": competitionTSS,
            "secondsInZone": {competitionZone: targetTimeInSeconds},
            "theoreticalDistance": raceInfo["raceDistanceKm"],
            "theoreticalTime": timedelta(seconds=targetTimeInSeconds),
        }]
        if futureMicrocycle["endDate"].weekday() >= 1:
            dayByDay[weekDaysMapping[futureMicrocycle["endDate"].weekday()-1]] = [{
                "workoutType": "Activation",
                "activity": raceInfo["mainSport"],
                "tss": competitionTSS,
                "secondsInZone": {1: 1800, 6: 120},
                "theoreticalDistance": 5,
                "theoreticalTime": timedelta(seconds=1920),
            }]

        
        
        # if the duration of the microcycle is more than 5 days, d-2, d-3, d-4 is a rest day, but d-5 is a very long zone 2, about 60% of the long workout
        if (futureMicrocycle["endDate"] - futureMicrocycle["startDate"])>timedelta(days=5):
            tz1 = loadsInfo["finalLongRunTSS"]*0.5*0.3 / TSS_BY_ZONE_BY_SPORT[raceInfo["mainSport"]][1]*3600
            tz2 = loadsInfo["finalLongRunTSS"]*0.5*0.7 / TSS_BY_ZONE_BY_SPORT[raceInfo["mainSport"]][2]*3600
            theoreticalDistance = tz1 / 3600 * SPEED_BY_ZONE_BY_SPORT_BY_ATHLETE_LEVEL_KMH[raceInfo["mainSport"]][raceInfo["fitnessLevel"]][1] + tz2 / 3600 * SPEED_BY_ZONE_BY_SPORT_BY_ATHLETE_LEVEL_KMH[raceInfo["mainSport"]][raceInfo["fitnessLevel"]][2]
            dayByDay[weekDaysMapping[futureMicrocycle["endDate"].weekday()-5]] = [{
                "workoutType": "Long",
                "activity": raceInfo["mainSport"],
                "tss": loadsInfo["finalLongRunTSS"]*0.5,
                "secondsInZone": {1: tz1, 2: tz2},
                "theoreticalDistance": theoreticalDistance,
                "theoreticalTime": timedelta(seconds=tz1 + tz2),
            }]
        remaining_tss = 0
        futureMicrocycle["dayByDay"] = dayByDay
        return futureMicrocycle
    
    if "Long" in futureMicrocycle.get("keyWorkouts", []):
        log_debug("Planning long workout")
        # let's split futureMicrocycle["theoreticalLongWorkoutTSS"] TSS in zones 1 2 and 3 with 30% 50% and 20% of the time respectively

        z1Percentage = 0.3
        z2Percentage = 0.5
        z3Percentage = 0.2
        
        intervalsSuggestions = []

        tz1 = (
            futureMicrocycle["theoreticalLongWorkoutTSS"]
            * 3600
            / (
                TSS_BY_ZONE_BY_SPORT[raceInfo["mainSport"]][1]
                + TSS_BY_ZONE_BY_SPORT[raceInfo["mainSport"]][2]
                * (z1Percentage / z2Percentage)
                + TSS_BY_ZONE_BY_SPORT[raceInfo["mainSport"]][3]
                * (z1Percentage / z3Percentage)
            )
        )
        tz2 = tz1 * z1Percentage / z2Percentage
        tz3 = tz1 * z1Percentage / z3Percentage

        if theoreticalTimeInZone[3] < tz3:
            # Rebalance to zone 2
            tz2 += (
                (tz3 - theoreticalTimeInZone[3])
                * TSS_BY_ZONE_BY_SPORT[raceInfo["mainSport"]][3]
                / TSS_BY_ZONE_BY_SPORT[raceInfo["mainSport"]][2]
            )

        # Compute the theoretical distance run
        theoreticalDistance = (
            tz1
            / 3600
            * SPEED_BY_ZONE_BY_SPORT_BY_ATHLETE_LEVEL_KMH[raceInfo["mainSport"]][
                raceInfo["fitnessLevel"]
            ][1]
            + tz2
            / 3600
            * SPEED_BY_ZONE_BY_SPORT_BY_ATHLETE_LEVEL_KMH[raceInfo["mainSport"]][
                raceInfo["fitnessLevel"]
            ][2]
            + tz3
            / 3600
            * SPEED_BY_ZONE_BY_SPORT_BY_ATHLETE_LEVEL_KMH[raceInfo["mainSport"]][
                raceInfo["fitnessLevel"]
            ][3]
        )

        activity_tss = (
            tz1 / 3600 * TSS_BY_ZONE_BY_SPORT[raceInfo["mainSport"]][1]
            + tz2 / 3600 * TSS_BY_ZONE_BY_SPORT[raceInfo["mainSport"]][2]
            + tz3 / 3600 * TSS_BY_ZONE_BY_SPORT[raceInfo["mainSport"]][3]
        )
        
        # take half of the tz1 as a warmup in intervals suggestions
        intervalsSuggestions.append({
            "intervalType": "Warmup",
            "description": "Warmup",
            "duration": tz1/2,
            "zone": 1,
            "tss": tz1/2/3600*TSS_BY_ZONE_BY_SPORT[raceInfo["mainSport"]][1],
            "secondsInZone": {1: tz1/2}
        })
        # take a third of tz2 next
        intervalsSuggestions.append({
            "intervalType": "Main",
            "description": "Main",
            "duration": tz2/3,
            "zone": 2,
            "tss": tz2/3/3600*TSS_BY_ZONE_BY_SPORT[raceInfo["mainSport"]][2],
            "secondsInZone": {2: tz2/3}
        })
        #then half of tz3
        intervalsSuggestions.append({
            "intervalType": "Main",
            "description": "Main",
            "duration": tz3/2,
            "zone": 3,
            "tss": tz3/2/3600*TSS_BY_ZONE_BY_SPORT[raceInfo["mainSport"]][3],
            "secondsInZone": {3: tz3/2}
        })
        #then another third of tz2
        intervalsSuggestions.append({
            "intervalType": "Main",
            "description": "Main",
            "duration": tz2/3,
            "zone": 2,
            "tss": tz2/3/3600*TSS_BY_ZONE_BY_SPORT[raceInfo["mainSport"]][2],
            "secondsInZone": {2: tz2/3}
        })
        # then rest of tz3
        intervalsSuggestions.append({
            "intervalType": "Main",
            "description": "Main",
            "duration": tz3/2,
            "zone": 3,
            "tss": tz3/2/3600*TSS_BY_ZONE_BY_SPORT[raceInfo["mainSport"]][3],
            "secondsInZone": {3: tz3/2}
        })
        # rest of tz2
        intervalsSuggestions.append({
            "intervalType": "Main",
            "description": "Main",
            "duration": tz2/3,
            "zone": 2,
            "tss": tz2/3/3600*TSS_BY_ZONE_BY_SPORT[raceInfo["mainSport"]][2],
            "secondsInZone": {2: tz2/3}
        })
        # rest of tz1
        intervalsSuggestions.append({
            "intervalType": "Cooldown",
            "description": "Cooldown",
            "duration": tz1/2,
            "zone": 1,
            "tss": tz1/2/3600*TSS_BY_ZONE_BY_SPORT[raceInfo["mainSport"]][1],
            "secondsInZone": {1: tz1/2}
        })

        dayByDay[weekInfo["longWorkoutDay"]] = [
            {
                "workoutType": "Long",
                "activity": raceInfo["mainSport"],
                "tss": activity_tss,
                "secondsInZone": {1: tz1, 2: tz2, 3: tz3},
                "theoreticalDistance": theoreticalDistance,
                "theoreticalTime": timedelta(seconds=tz1 + tz2 + tz3),
                "intervalSuggestions": intervalsSuggestions
            }
        ]

        remaining_tss -= activity_tss

        theoreticalTimeInZone[1] -= tz1
        theoreticalTimeInZone[2] -= tz2
        theoreticalTimeInZone[3] -= tz3
        if weekInfo["longWorkoutDay"] in availableDays:
            availableDays.remove(weekInfo["longWorkoutDay"])
            dayAvailableDurations[weekInfo["longWorkoutDay"]] -= tz1 + tz2 + tz3
        log_debug(dayByDay)

    remaining_number_of_workouts = round(
        remaining_tss
        / REGULAR_WORKOUT_TSS_BY_SPORT_BY_OBJECTIVE_BY_OBJECTIVE_SIZE_BY_ATHLETE_LEVEL[
            raceInfo["mainSport"]
        ][raceInfo["objective"]][raceInfo["eventSize"]][raceInfo["fitnessLevel"]]
    )
    if remaining_number_of_workouts == 0:
        futureMicrocycle["dayByDay"] = dayByDay
        return futureMicrocycle
    else:
        tss_per_activity = round(remaining_tss / remaining_number_of_workouts)

    if "ShortIntensity" in futureMicrocycle.get("keyWorkouts", []):
        log_debug("Planning short intensity workout")
        # let's split futureMicrocycle["theoreticalShortIntensityTSS"] TSS in zones 5 6 and 7 with 50% 30% and 20% of the time respectively

        total_tss, secondsInZone, intervalsSuggestions = createWorkout(
            loadsInfo["minTssPerWorkout"],
            loadsInfo["maxTssPerWorkout"],
            tss_per_activity,
            theoreticalTimeInZone,
            min_time_in_zones={},
            max_time_in_zones={5: 1200, 6: 600, 7: 300},
            cumulative_max_tss_in_zones=[
                {
                    "zones": [5, 6, 7],
                    "max": futureMicrocycle["theoreticalShortIntensityTSS"],
                }
            ],
            zones=[7, 6, 5],
            warmup_duration=600,
            cooldown_duration=600,
            activity=raceInfo["mainSport"],
        )
        log_debug(
            f"Short intensity workout, seconds in zone {secondsInZone}, total tss {total_tss}"
        )
        theoreticalDistance = sum(
            [
                secondsInZone[zone]
                / 3600
                * SPEED_BY_ZONE_BY_SPORT_BY_ATHLETE_LEVEL_KMH[raceInfo["mainSport"]][
                    raceInfo["fitnessLevel"]
                ][zone]
                for zone in ZONES[raceInfo["mainSport"]].keys()
            ]
        )

        # let's find the good day
        total_seconds = sum(
            [secondsInZone[zone] for zone in ZONES[raceInfo["mainSport"]].keys()]
        )
        best_fit = findBestFitDay(total_seconds, availableDays, dayAvailableDurations)
        if best_fit is not None:
            if dayByDay.get(best_fit[0], None) is None:
                dayByDay[best_fit[0]] = []
            dayByDay[best_fit[0]].append(
                {
                    "workoutType": "ShortIntensity",
                    "activity": raceInfo["mainSport"],
                    "tss": total_tss,
                    "secondsInZone": secondsInZone,
                    "theoreticalDistance": theoreticalDistance,
                    "theoreticalTime": timedelta(seconds=total_seconds),
                    "intervalSuggestions": intervalsSuggestions,
                }
            )
            for zone in ZONES[raceInfo["mainSport"]].keys():
                theoreticalTimeInZone[zone] -= secondsInZone[zone]

            dayAvailableDurations[best_fit[0]] -= total_seconds
            # if dayAvailableDurations[best_fit[0]] <= 0:
            availableDays.remove(best_fit[0])

        log_debug(dayByDay)
    if "LongIntensity" in futureMicrocycle.get("keyWorkouts", []):
        log_debug("Planning long intensity workout")
        total_tss, secondsInZone, intervalsSuggestions = createWorkout(
            loadsInfo["minTssPerWorkout"],
            loadsInfo["maxTssPerWorkout"],
            tss_per_activity,
            theoreticalTimeInZone,
            min_time_in_zones={},
            max_time_in_zones={4: 1800, 3: 7200},
            cumulative_max_tss_in_zones=[
                {
                    "zones": [4, 3],
                    "max": futureMicrocycle["theoreticalLongIntensityTSS"],
                }
            ],
            zones=[4, 3],
            warmup_duration=600,
            cooldown_duration=600,
            activity=raceInfo["mainSport"],
        )
        log_debug(
            f"Long intensity workout, seconds in zone {secondsInZone}, total tss {total_tss}"
        )
        theoreticalDistance = sum(
            [
                secondsInZone[zone]
                / 3600
                * SPEED_BY_ZONE_BY_SPORT_BY_ATHLETE_LEVEL_KMH[raceInfo["mainSport"]][
                    raceInfo["fitnessLevel"]
                ][zone]
                for zone in ZONES[raceInfo["mainSport"]].keys()
            ]
        )
        # let's find the good day
        total_seconds = sum(
            [secondsInZone[zone] for zone in ZONES[raceInfo["mainSport"]].keys()]
        )
        best_fit = findBestFitDay(total_seconds, availableDays, dayAvailableDurations)
        if best_fit is not None:
            if dayByDay.get(best_fit[0], None) is None:
                dayByDay[best_fit[0]] = []
            dayByDay[best_fit[0]].append(
                {
                    "workoutType": "LongIntensity",
                    "activity": raceInfo["mainSport"],
                    "tss": total_tss,
                    "secondsInZone": secondsInZone,
                    "theoreticalDistance": theoreticalDistance,
                    "theoreticalTime": timedelta(seconds=total_seconds),
                    "intervalSuggestions": intervalsSuggestions,
                }
            )
            for zone in ZONES[raceInfo["mainSport"]].keys():
                theoreticalTimeInZone[zone] -= secondsInZone[zone]

            dayAvailableDurations[best_fit[0]] -= total_seconds
            # if dayAvailableDurations[best_fit[0]] <= 0:
            availableDays.remove(best_fit[0])
        log_debug(dayByDay)

    if "RaceIntensity" in futureMicrocycle.get("keyWorkouts", []):
        log_debug("Planning race intensity workout")
        total_tss, secondsInZone, intervalsSuggestions = createWorkout(
            loadsInfo["minTssPerWorkout"],
            loadsInfo["maxTssPerWorkout"],
            tss_per_activity,
            theoreticalTimeInZone,
            min_time_in_zones={},
            max_time_in_zones={raceInfo["raceZone"]: 1800},
            zones=[raceInfo["raceZone"]],
            warmup_duration=600,
            cooldown_duration=600,
            activity=raceInfo["mainSport"],
        )
        theoreticalDistance = sum(
            [
                secondsInZone[zone]
                / 3600
                * SPEED_BY_ZONE_BY_SPORT_BY_ATHLETE_LEVEL_KMH[raceInfo["mainSport"]][
                    raceInfo["fitnessLevel"]
                ][zone]
                for zone in ZONES[raceInfo["mainSport"]].keys()
            ]
        )
        total_seconds = sum(
            [secondsInZone[zone] for zone in ZONES[raceInfo["mainSport"]].keys()]
        )
        best_fit = findBestFitDay(total_seconds, availableDays, dayAvailableDurations)
        if best_fit is not None:
            if dayByDay.get(best_fit[0], None) is None:
                dayByDay[best_fit[0]] = []
            dayByDay[best_fit[0]].append(
                {
                    "workoutType": "RaceIntensity",
                    "activity": raceInfo["mainSport"],
                    "tss": total_tss,
                    "secondsInZone": secondsInZone,
                    "theoreticalDistance": theoreticalDistance,
                    "theoreticalTime": timedelta(seconds=total_seconds),
                    "intervalSuggestions": intervalsSuggestions,
                }
            )
            for zone in ZONES[raceInfo["mainSport"]].keys():
                theoreticalTimeInZone[zone] -= secondsInZone[zone]

            dayAvailableDurations[best_fit[0]] -= total_seconds
            # if dayAvailableDurations[best_fit[0]] <= 0:
            availableDays.remove(best_fit[0])
        log_debug(dayByDay)
    remaining_tss = futureMicrocycle["theoreticalWeeklyTSS"] - sum(
        [workout["tss"] for day in dayByDay.values() for workout in day]
    )
    # Let's plan the remaining time in zones
    while remaining_tss > 30:
        log_debug("Planning a new workout")
        zones = []
        for zone in ZONES[raceInfo["mainSport"]].keys():
            if theoreticalTimeInZone[zone] > 0:
                zones.append(zone)
        zones = sorted(zones, key=lambda x: x, reverse=True)

        total_tss, secondsInZone, intervalsSuggestions = createWorkout(
            loadsInfo["minTssPerWorkout"],
            100,
            tss_per_activity,
            theoreticalTimeInZone,
            min_time_in_zones={},
            max_time_in_zones={},
            cumulative_max_tss_in_zones=[{"zones": [3, 4, 5, 6, 7], "max": 40}],
            zones=zones,
            warmup_duration=600,
            cooldown_duration=600,
            activity=raceInfo["mainSport"],
        )
        log_debug(f"New workout, seconds in zone {secondsInZone}, total tss {total_tss}")

        theoreticalDistance = sum(
            [
                secondsInZone[zone]
                / 3600
                * SPEED_BY_ZONE_BY_SPORT_BY_ATHLETE_LEVEL_KMH[raceInfo["mainSport"]][
                    raceInfo["fitnessLevel"]
                ][zone]
                for zone in ZONES[raceInfo["mainSport"]].keys()
            ]
        )
        total_seconds = sum(
            [secondsInZone[zone] for zone in ZONES[raceInfo["mainSport"]].keys()]
        )
        best_fit = findBestFitDay(total_seconds, availableDays, dayAvailableDurations)
        log_debug("Best fit")
        log_debug(best_fit)
        if best_fit is not None:
            if dayByDay.get(best_fit[0], None) is None:
                dayByDay[best_fit[0]] = []
            dayByDay[best_fit[0]].append(
                {
                    "workoutType": "Remaining",
                    "activity": raceInfo["mainSport"],
                    "tss": total_tss,
                    "secondsInZone": secondsInZone,
                    "theoreticalDistance": theoreticalDistance,
                    "theoreticalTime": timedelta(seconds=total_seconds),
                    "intervalSuggestions": intervalsSuggestions,
                }
            )
            for zone in ZONES[raceInfo["mainSport"]].keys():
                theoreticalTimeInZone[zone] -= secondsInZone[zone]

            dayAvailableDurations[best_fit[0]] -= total_seconds
            if best_fit[0] in availableDays:
                availableDays.remove(best_fit[0])
        remaining_tss -= total_tss

        log_debug(dayByDay)

    futureMicrocycle["dayByDay"] = dayByDay

    return futureMicrocycle


def findBestFitDay(total_seconds, available_days, available_durations):
    log_debug(
        f"Finding best fit day, total seconds: {total_seconds}, available days: {available_days}, available durations: {available_durations}"
    )
    best_fit = None
    if len(available_days) == 0:
        # find the one that has the most available duration
        for day in available_durations.keys():
            if best_fit is None:
                best_fit = (day, available_durations[day])
            elif available_durations[day] > best_fit[1]:
                best_fit = (day, available_durations[day])
    else:
        for day in available_days:
            duration = available_durations[day]
            if duration >= total_seconds:
                if best_fit is None:
                    best_fit = (day, duration)
                elif duration < best_fit[1]:
                    best_fit = (day, duration)
    log_debug(f"Best fit day: {best_fit}")
    return best_fit


def createWorkout(
    min_tss,
    max_tss,
    target_tss,
    remaining_time_in_zone,
    min_time_in_zones,
    max_time_in_zones,
    cumulative_max_tss_in_zones=[],
    zones=[3, 2, 1],
    warmup_duration=1200,
    cooldown_duration=600,
    activity="Run",
):
    log_debug("Creating workout with params: ")
    log_debug(
        f"min_tss: {min_tss}, max_tss: {max_tss}, target_tss: {target_tss}, remaining_time_in_zone: {remaining_time_in_zone}, min_time_in_zones: {min_time_in_zones}, max_time_in_zones: {max_time_in_zones}, cumulative_max_tss_in_zones: {cumulative_max_tss_in_zones}, zones: {zones}, warmup_duration: {warmup_duration}, cooldown_duration: {cooldown_duration}, activity: {activity}"
    )
    total_tss = 0
    secondsInZone = {zone: 0 for zone in ZONES[activity].keys()}
    intervalsSuggestions = []
    remaining_tss = target_tss
    log_debug("TSS to reach")
    log_debug(remaining_tss)

    # Warmup
    secondsInZone[1] = warmup_duration
    warmup_tss = round(TSS_BY_ZONE_BY_SPORT[activity][1] * warmup_duration / 3600)
    total_tss += warmup_tss
    remaining_tss -= warmup_tss
    intervalsSuggestions.append(
        {
            "intervalType": "Warmup",
            "description": "Warmup",
            "zone": 1,
            "tss": warmup_tss,
            "secondsInZone": {1: warmup_duration},
        }
    )

    # Cooldown
    secondsInZone[1] = secondsInZone[1] + cooldown_duration
    cooldown_tss = round(TSS_BY_ZONE_BY_SPORT[activity][1] * cooldown_duration / 3600)
    total_tss += cooldown_tss
    remaining_tss -= cooldown_tss

    log_debug("Remaining TSS after warmup and cooldown")
    log_debug(remaining_tss)

    for zone in zones:
        log_debug(f"Zone {zone}, remaining time in zone {remaining_time_in_zone[zone]}")
        if remaining_time_in_zone[zone] > 0:
            # Depending on zone, we also add some associated Z1 rest time to recover between intervals
            recovery_factor = ZONE_RECOVERY_FACTOR_BY_SPORT[activity][zone]
            max_seconds_in_remaining_tss = (
                3600
                * remaining_tss
                / (
                    TSS_BY_ZONE_BY_SPORT[activity][zone]
                    + recovery_factor * TSS_BY_ZONE_BY_SPORT[activity][1]
                )
            )

            # take into account cumulative max tss in zones
            biggest_constraint_from_cumulative_max_tss = 99999999
            for constraint in cumulative_max_tss_in_zones:
                if zone in constraint["zones"]:
                    log_debug("Constraint")
                    log_debug(constraint)
                    other_zones = [z for z in constraint["zones"] if z != zone]
                    log_debug("Other zones")
                    log_debug(other_zones)
                    other_zones_tss = sum(
                        [
                            TSS_BY_ZONE_BY_SPORT[activity][z] * secondsInZone[z] / 3600
                            for z in other_zones
                        ]
                    )
                    log_debug("Other zones tss")
                    log_debug(other_zones_tss)
                    constraint_associated_tss = constraint["max"] - other_zones_tss
                    log_debug("Constraint associated tss")
                    log_debug(constraint_associated_tss)
                    associated_time_in_seconds = (
                        constraint_associated_tss
                        * 3600
                        / TSS_BY_ZONE_BY_SPORT[activity][zone]
                    )
                    log_debug("Associated time")
                    log_debug(associated_time_in_seconds)
                    if (
                        associated_time_in_seconds
                        < biggest_constraint_from_cumulative_max_tss
                    ):
                        biggest_constraint_from_cumulative_max_tss = (
                            associated_time_in_seconds
                        )

            log_debug(
                f"min time in zone {min_time_in_zones.get(zone, 0)}, max time in zone {max_time_in_zones.get(zone, 9999999)}, remaining time in zone {remaining_time_in_zone[zone]}, max seconds in remaining tss {max_seconds_in_remaining_tss}, biggest constraint from cumulative max tss {biggest_constraint_from_cumulative_max_tss}"
            )

            seconds_in_zone = round(
                min(
                    biggest_constraint_from_cumulative_max_tss,
                    remaining_time_in_zone[zone],
                    max_seconds_in_remaining_tss,
                )
            )

            tss = round(TSS_BY_ZONE_BY_SPORT[activity][zone] * seconds_in_zone / 3600)
            total_tss += tss
            remaining_tss -= tss
            secondsInZone[zone] = round(secondsInZone[zone] + seconds_in_zone)

            # Add recovery time
            secondsInZone[1] = secondsInZone[1] + seconds_in_zone * recovery_factor
            recovery_tss = round(
                TSS_BY_ZONE_BY_SPORT[activity][1]
                * seconds_in_zone
                * recovery_factor
                / 3600
            )
            total_tss += recovery_tss
            remaining_tss -= recovery_tss
            
            numberOfIntervals = int(seconds_in_zone/TYPICAL_DURATION_FOR_INTERVALS_BY_ZONE_BY_SPORT[activity][zone])+1
            if numberOfIntervals > 0:
                secondsInIntervals = round(seconds_in_zone / numberOfIntervals)
            else:
                secondsInIntervals = 0
            log_debug(f"Zone: {zone}, Number of intervals: {numberOfIntervals}, seconds in intervals: {secondsInIntervals}")
            for i in range(numberOfIntervals):
                intervalsSuggestions.append(
                    {
                        "intervalType": "Interval",
                        "description": f"Interval {i+1}",
                        "zone": zone,
                        "tss": round(tss/numberOfIntervals),
                        "secondsInZone": {zone: secondsInIntervals},
                    }
                )
                intervalsSuggestions.append(
                    {
                        "intervalType": "Recovery",
                        "description": f"Recovery {i+1}",
                        "zone": 1,
                        "tss": round(recovery_tss/numberOfIntervals),
                        "secondsInZone": {1: secondsInIntervals},
                    }
                )
            
            
            
            
            log_debug(
                f"seconds_in_zone {seconds_in_zone}, tss {tss}, recovery_tss {recovery_tss}"
            )

    # if we are under the min tss, we add half Z1 half Z2 time
    if remaining_tss > 0:
        log_debug("Adding z1 and Z2 time")
        log_debug("Remaining TSS for this activity: ")
        log_debug(remaining_tss)
        log_debug("Remaining time in zone")
        log_debug(remaining_time_in_zone)
        tssz1toadd = remaining_tss / 2
        tssz2toadd = remaining_tss / 2
        secondsInZone[1] = secondsInZone[1] + round(
            tssz1toadd * 3600 / TSS_BY_ZONE_BY_SPORT[activity][1]
        )
        secondsInZone[2] = secondsInZone[2] + round(
            tssz2toadd * 3600 / TSS_BY_ZONE_BY_SPORT[activity][2]
        )
        total_tss += remaining_tss
        remaining_tss = 0
        
        # add the z2 between the warmup and the first interval, and the z1 after the last interval
        intervalsSuggestions.insert(1,
            {
                "intervalType": "Z2",
                "description": "Z2",
                "zone": 2,
                "tss": round(tssz2toadd),
                "secondsInZone": {2: round(tssz2toadd * 3600 / TSS_BY_ZONE_BY_SPORT[activity][2])},
            }
        )
        intervalsSuggestions.append(
            {
                "intervalType": "Z1",
                "description": "Z1",
                "zone": 1,
                "tss": round(tssz1toadd),
                "secondsInZone": {1: round(tssz1toadd * 3600 / TSS_BY_ZONE_BY_SPORT[activity][1])},
            }
        )
        
    intervalsSuggestions.append(
        {
            "intervalType": "Cooldown",
            "description": "Cooldown",
            "zone": 1,
            "tss": cooldown_tss,
            "secondsInZone": {1: cooldown_duration},
        }
    )

    return total_tss, secondsInZone, intervalsSuggestions


def currentLoadStatus(pastMicrocycles, cycleLength=4, mainSport="Run"):
    currentHandableLoad = 0
    lastRestingWeek = 0
    missingKeyWorkouts = []
    TSSBalance = 0
    nextWeekGuidelines = []
    TSSPerZoneBalance = {zone: 0 for zone in ZONES[mainSport].keys()}
    biggestWorkout = 0
    biggestRaceIntensity = 0
    biggestLongIntensityWorkout = 0
    biggestShortIntensityWorkout = 0

    for week in pastMicrocycles[-4:]:
        if "actualTSS" in week:
            if week["actualTSS"] > currentHandableLoad:
                currentHandableLoad = week["actualTSS"]
    # let's look backward in pastMicrocycles to find the last resting week
    for i, week in enumerate(pastMicrocycles):
        if week["actualResting"]:
            lastRestingWeek = i
            break
    nextRestingWeek = max(
        min(cycleLength - (len(pastMicrocycles) - lastRestingWeek), cycleLength), 0
    )

    for week in pastMicrocycles[-2:]:
        if "keyWorkoutsMissing" in week:
            for workout in week["keyWorkoutsMissing"]:
                missingKeyWorkouts.append(workout)
    for week in pastMicrocycles[-5:]:
        TSSBalance += week["actualTSS"] - week["theoreticalWeeklyTSS"]

    if len(pastMicrocycles) > 0:
        nextWeekGuidelines = pastMicrocycles[-1]["nextWeekGuidelines"]
    else:
        nextWeekGuidelines = "Normal"

    for week in pastMicrocycles[-4:]:
        TSSPerZoneBalance = {
            zone: TSSPerZoneBalance[zone]
            + week["deltaTimeInZone"][zone]
            * TSS_BY_ZONE_BY_SPORT[mainSport][zone]
            / 3600
            for zone in ZONES[mainSport].keys()
        }

    for week in pastMicrocycles[-3:]:
        if week["longWorkoutDone"]:
            biggestWorkout = max(week["theoreticalLongWorkoutTSS"], biggestWorkout)
        else:
            biggestWorkout = max(week["actualLongWorkoutTSS"], biggestWorkout)
        if week["RaceIntensityDone"]:
            biggestRaceIntensity = max(
                week["theoreticalRaceIntensityTSS"], biggestRaceIntensity
            )
        else:
            biggestRaceIntensity = max(
                week["actualRaceIntensityTSS"], biggestRaceIntensity
            )
        if week["LongIntensityDone"]:
            biggestLongIntensityWorkout = max(
                week["theoreticalLongIntensityTSS"], biggestLongIntensityWorkout
            )
        else:
            biggestLongIntensityWorkout = max(
                week["actualLongIntensityTSS"], biggestLongIntensityWorkout
            )
        if week["ShortIntensityDone"]:
            biggestShortIntensityWorkout = max(
                week["theoreticalShortIntensityTSS"], biggestShortIntensityWorkout
            )
        else:
            biggestShortIntensityWorkout = max(
                week["actualShortIntensityTSS"], biggestShortIntensityWorkout
            )

    return {
        "currentHandableLoad": currentHandableLoad,
        "nextRestingWeek": nextRestingWeek,
        "missingKeyWorkouts": missingKeyWorkouts,
        "TSSBalance": TSSBalance,
        "nextWeekGuidelines": nextWeekGuidelines,
        "TSSPerZoneBalance": TSSPerZoneBalance,
        "biggestWorkout": biggestWorkout,
        "biggestRaceIntensity": biggestRaceIntensity,
        "biggestLongIntensityWorkout": biggestLongIntensityWorkout,
        "biggestShortIntensityWorkout": biggestShortIntensityWorkout,
    }


def compareCurrentWeekWithPlannedWeekAndReplanIfNeeded(
    completedWorkouts,
    currentMicrocycle,
    startLoad,
    currentDay,
    lastWeeksTakeaways,
    maxTssPerDay=200,
    mainSport="Run",
):
    # variable days begins at currentday and goes up to 6
    remainingDays = [currentDay + i for i in range(6 - currentDay)]
    dayByDay = currentMicrocycle["dayByDay"]
    theroeticalTimeSpentWeekInSeconds = currentMicrocycle["theoreticalWeeklyTSS"] / sum(
        [
            TSS_BY_ZONE_BY_SPORT[mainSport][zone]
            * currentMicrocycle["timeInZoneRepartition"][zone]
            / 3600
            for zone in ZONES[mainSport].keys()
        ]
    )
    theroetical_time_in_zone = {zone: 0 for zone in ZONES[mainSport].keys()}
    for zone in ZONES[mainSport].keys():
        theroetical_time_in_zone[zone] = (
            currentMicrocycle["timeInZoneRepartition"][zone]
            * theroeticalTimeSpentWeekInSeconds
        )
    theoretical_time_in_zone_to_current_day = {
        zone: 0 for zone in ZONES[mainSport].keys()
    }
    for day in dayByDay:
        if day < currentDay:
            for workout in dayByDay[day]:
                for zone in workout["secondsInZone"].keys():
                    theoretical_time_in_zone_to_current_day[zone] += workout[
                        "secondsInZone"
                    ][zone]
    onTrack = True
    missingKeyWorkouts = []
    missingWorkouts = []
    nextWeekGuidelines = ""
    weekWorkouts = [
        workout
        for workout in completedWorkouts
        if workout["date"] >= currentMicrocycle["startDate"]
        and workout["date"] <= currentMicrocycle["endDate"]
    ]

    done_time_in_zone = {zone: 0 for zone in ZONES[mainSport].keys()}
    for workout in weekWorkouts:
        for zone in workout["secondsInZone"].keys():
            done_time_in_zone[zone] += workout["secondsInZone"][zone]

    remaining_time_in_zone = {
        zone: theroetical_time_in_zone[zone] - done_time_in_zone[zone]
        for zone in ZONES[mainSport].keys()
    }

    # The key workouts that we should have already done
    past_theoretical_key_workouts = []
    for workout in currentMicrocycle["keyWorkouts"]:
        # find the theoretical workout in the dayByDay
        for day in dayByDay:
            if day < currentDay:
                for plannedWorkout in dayByDay[day]:
                    if plannedWorkout["workoutType"] == workout:
                        past_theoretical_key_workouts.append(plannedWorkout)

    past_theoretical_workouts = []
    for day in dayByDay:
        if day < currentDay:
            for workout in dayByDay[day]:
                past_theoretical_workouts.append(workout)

    weekWorkoutsSuppl = weekWorkouts.copy()
    # check if the key workouts were done
    for workout in past_theoretical_key_workouts:
        done = False
        for actualWorkout in weekWorkoutsSuppl:
            if checkWorkoutValidity(actualWorkout, workout) > 0.8:
                done = True
                # remove the workout from the weekWorkoutsSuppl
                weekWorkoutsSuppl.remove(actualWorkout)
                break
        if not done:
            if workout["workoutType"] in currentMicrocycle["keyWorkouts"]:
                missingKeyWorkouts.append(workout)
    for workout in past_theoretical_workouts:
        done = False
        for actualWorkout in weekWorkoutsSuppl:
            if checkWorkoutValidity(actualWorkout, workout) > 0.8:
                done = True
                # remove the workout from the weekWorkoutsSuppl
                weekWorkoutsSuppl.remove(actualWorkout)
                break
        if not done:
            missingWorkouts.append(workout)

    # weekWorkoutsSuppl contains the workouts that were not planned.

    # Check if we have to high difference in the time in zone to this day, and if yes, replan
    difference_time_in_zone = {
        zone: theoretical_time_in_zone_to_current_day[zone] - done_time_in_zone[zone]
        for zone in ZONES[mainSport].keys()
    }

    planned_activities_lost = []
    # Treat the key workouts first and try replanning it if failed
    for keyWorkout in currentMicrocycle["keyWorkouts"]:
        if keyWorkout in missingKeyWorkouts:
            # find the keyWorkout in the dayByDay
            for day in dayByDay:
                for workout in dayByDay[day]:
                    if workout["workoutType"] == keyWorkout:
                        keyWorkoutActivity = workout

            bestDay = findBestDayToReplace(
                dayByDay, currentMicrocycle["keyWorkouts"], keyWorkout, remainingDays
            )
            activitiesLost = dayByDay[bestDay]
            for activity in activitiesLost:
                planned_activities_lost.append(activity)
            dayByDay[bestDay] = [keyWorkoutActivity]

    # Treat the other workouts
    for workout in missingWorkouts:
        bestDay = findBestDayToReplace(
            dayByDay, currentMicrocycle["keyWorkouts"], workout, remainingDays
        )
        if bestDay:
            activitiesLost = dayByDay[bestDay]
            for activity in activitiesLost:
                planned_activities_lost.append(activity)
            dayByDay[bestDay] = [workout]

    # check the state of the new plan, with the completed activities and the remaining planned activities after these changes
    newPlannedTSS = sum(
        [workout["tss"] for day in dayByDay for workout in dayByDay[day]]
    ) + sum([workout["tss"] for workout in weekWorkouts])
    tss_difference = newPlannedTSS - currentMicrocycle["theoreticalWeeklyTSS"]

    missingWorkoutsCopy = missingWorkouts.copy()
    planned_activities_lost_copy = planned_activities_lost.copy()

    while (
        tss_difference > currentMicrocycle["theoreticalWeeklyTSS"] / 7
    ):  # If we miss more than 1 day of TSS, we have to add back a missing workout
        # add back a missingWorkouts or a planned_activity_lost if we can find a day that when we add is not more than loadsInfo["maxTssPerDay"]
        for missingWorkout in missingWorkouts:
            for day in dayByDay:
                if day > currentDay:
                    dayTss = sum([workout["tss"] for workout in dayByDay[day]])
                    if (
                        dayTss + missingWorkout["tss"] < maxTssPerDay
                    ):  # if this workout can feet in this day
                        dayByDay[day].append(missingWorkout)
                        missingWorkouts.remove(missingWorkout)
                        tss_difference -= missingWorkout["tss"]
                        break
            missingWorkouts.remove(
                missingWorkout
            )  # we did not manage to replan it, so remove it from the missingWorkouts
        for (
            activity
        ) in planned_activities_lost:  # do the same with the planned_activities_lost
            for day in dayByDay:
                if day > currentDay:
                    dayTss = sum([workout["tss"] for workout in dayByDay[day]])
                    if dayTss + activity["tss"] < maxTssPerDay:
                        dayByDay[day].append(activity)
                        planned_activities_lost.remove(activity)
                        tss_difference -= activity["tss"]
                        break
            planned_activities_lost.remove(activity)
        if not missingWorkouts and not planned_activities_lost:
            break

    newPlannedTimeInZone = {zone: 0 for zone in ZONES[mainSport].keys()}
    for day in dayByDay:  # take the future plan
        if day > currentDay:
            for workout in dayByDay[day]:
                for zone in workout["secondsInZone"].keys():
                    newPlannedTimeInZone[zone] += workout["secondsInZone"][zone]
    for workout in weekWorkouts:
        for zone in workout["secondsInZone"].keys():
            newPlannedTimeInZone[zone] += workout["secondsInZone"][zone]
    time_in_zone_difference = {
        zone: newPlannedTimeInZone[zone] - theroetical_time_in_zone[zone]
        for zone in ZONES[mainSport].keys()
    }

    for zone in ZONES[mainSport].keys():
        # check also if the lastWeeksTakeaways["TSSPerZoneBalance"] does not compensate
        if (
            abs(time_in_zone_difference[zone]) > 0.1 * theroetical_time_in_zone[zone]
            and abs(
                lastWeeksTakeaways["TSSPerZoneBalance"][zone]
                + time_in_zone_difference[zone]
            )
            < 0.1 * theroetical_time_in_zone[zone]
        ):
            # find remaining activities that have this zone and replan accordingly to the difference
            activities_having_this_zone = []
            for day in dayByDay:
                if day > currentDay:
                    for workout in dayByDay[day]:
                        if workout["secondsInZone"][zone] > 0:
                            activities_having_this_zone.append(workout)

            if (
                len(activities_having_this_zone) == 0
                and time_in_zone_difference[zone] > 0
            ):
                # insert it in any easy workout
                for day in dayByDay:
                    if day > currentDay:
                        for workout in dayByDay[day]:
                            if workout["workoutType"] == "Easy":
                                workout["secondsInZone"][zone] += (
                                    time_in_zone_difference[zone]
                                )
                                tss_change = (
                                    time_in_zone_difference[zone]
                                    * TSS_BY_ZONE_BY_SPORT[workout["activity"]][zone]
                                    / 3600
                                )
                                workout["tss"] += tss_change
            elif len(activities_having_this_zone) > 0:
                shared_load = time_in_zone_difference[zone] / len(
                    activities_having_this_zone
                )
                for activity in activities_having_this_zone:
                    # but keep minimum 0
                    to_add_or_remove = max(
                        shared_load, -activity["secondsInZone"][zone]
                    )
                    activity["secondsInZone"][zone] += to_add_or_remove
                    tss_change = (
                        TSS_BY_ZONE_BY_SPORT[activity["activity"]][zone]
                        / 3600
                        * to_add_or_remove
                    )
                    activity["tss"] += tss_change

    if currentMicrocycle["theoreticalResting"]:
        # Check if we are not already higher than the planned TSS
        if (
            sum([workout["tss"] for workout in completedWorkouts])
            > 1.3 * currentMicrocycle["theoreticalWeeklyTSS"]
        ):
            onTrack = False
            if nextWeekGuidelines == "":
                nextWeekGuidelines = "rest"

    currentMicrocycle["onTrack"] = onTrack
    currentMicrocycle["missingKeyWorkouts"] = missingKeyWorkouts
    currentMicrocycle["nextWeekGuidelines"] = nextWeekGuidelines


def findBestDayToReplace(
    dayByDay, microcycleKeyWorkouts, workoutToReschedule, remainingDays
):
    # first look for a rest day
    for day in remainingDays:
        if not dayByDay[day]:
            return day
    for day in remainingDays:
        # if we have only an easy workout, replace it
        if len(dayByDay[day]) == 1 and dayByDay[day][0]["workoutType"] == "Easy":
            return day
    if workoutToReschedule in microcycleKeyWorkouts:
        # else look for a less important day
        days_score = {day: 0 for day in remainingDays}
        for day in remainingDays:
            types = [workout["workoutType"] for workout in dayByDay[day]]
            # if there is one type of types that is before in the list of microcycleKeyWorkouts than keyWorkout add a score of the difference of the indexes
            for i, workout in enumerate(microcycleKeyWorkouts):
                if workout in types:
                    days_score[day] += i - types.index(workout)
        return min(days_score, key=days_score.get)
    else:
        return None


def update_macrocycle(macrocycle, new_values):
    # Store the current state before updating
    previous_version = {
        "startDate": macrocycle.get("startDate"),
        "endDate": macrocycle.get("endDate"),
        "totalTSS": macrocycle.get("totalTSS"),
        "cycleLength": macrocycle.get("cycleLength"),
        "cycleType": macrocycle.get("cycleType"),
        "cycleNumber": macrocycle.get("cycleNumber"),
        "analyzed": macrocycle.get("analyzed"),
        "updateDate": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # Append to previousVersion if there is an update
    if "previousVersion" not in macrocycle:
        macrocycle["previousVersion"] = []

    if any(macrocycle.get(key) != new_values.get(key) for key in new_values):
        macrocycle["previousVersion"].append(previous_version)

    # Update the macrocycle with new values
    macrocycle.update(new_values)

    return macrocycle


def update_microcycle(microcycle, new_values):
    # Store the current state before updating
    previous_version = {
        "startDate": microcycle.get("startDate"),
        "endDate": microcycle.get("endDate"),
        "theoreticalWeeklyTSS": microcycle.get("theoreticalWeeklyTSS"),
        "theoreticalResting": microcycle.get("theoreticalResting"),
        "indexInCycle": microcycle.get("indexInCycle"),
        "keyWorkouts": microcycle.get("keyWorkouts"),
        "cycleType": microcycle.get("cycleType"),
        "cycleNumber": microcycle.get("cycleNumber"),
        "theoreticalLongWorkoutTSS": microcycle.get("theoreticalLongWorkoutTSS"),
        "theoreticalRaceIntensityTSS": microcycle.get("theoreticalRaceIntensityTSS"),
        "analyzed": microcycle.get("analyzed"),
        "timeInZoneRepartition": microcycle.get("timeInZoneRepartition"),
        "dayByDay": microcycle.get("dayByDay"),
        "updateDate": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # Append to previousVersion if there is an update
    if "previousVersion" not in microcycle:
        microcycle["previousVersion"] = []

    if any(microcycle.get(key) != new_values.get(key) for key in new_values):
        microcycle["previousVersion"].append(previous_version)

    # Update the microcycle with new values
    microcycle.update(new_values)

    return microcycle


def fix_ending(weeks, cycleLength):
    # Count how many worked weeks at the end
    worked_streak = 0
    for w in reversed(weeks):
        if w["theoreticalResting"]:
            break
        worked_streak += 1

    # Set allowed max to cycleLength - 1
    allowed_max = cycleLength - 1

    if worked_streak > allowed_max:
        # Convert some ending worked weeks to resting weeks
        to_convert = worked_streak - allowed_max
        for i in range(len(weeks) - 1, -1, -1):
            if to_convert <= 0:
                break
            w = weeks[i]
            if not w["theoreticalResting"]:
                w["theoreticalResting"] = True
                w["theoreticalWeeklyTSS"] = w["theoreticalWeeklyTSS"] * 0.6
                to_convert -= 1
    return weeks


def getSpecificWeeks(
    availableWeekNumber,
    load,
    cycleLength,
    nextRestingWeek,
    currentCycleNumber,
    currentIndexInCycle,
    is_top_level=True,
):
    if availableWeekNumber == 0:
        return []

    pattern = (
        ["W"] * nextRestingWeek + ["R"] + ["W"] * (cycleLength - nextRestingWeek - 1)
    )

    def build_week(week_type, cycle_num, index_in_cycle):
        if week_type == "R":
            return {
                "cycleType": "Specific",
                "cycleNumber": cycle_num,
                "indexInCycle": index_in_cycle,
                "theoreticalWeeklyTSS": load * 0.6,
                "theoreticalResting": True,
            }
        else:
            return {
                "cycleType": "Specific",
                "cycleNumber": cycle_num,
                "indexInCycle": index_in_cycle,
                "theoreticalWeeklyTSS": load,
                "theoreticalResting": False,
                "keyWorkouts": ["RaceIntensity", "Long", "ShortIntensity"],
            }

    def pattern_to_weeks(pat, cycle_num, start_idx):
        weeks = []
        for i, wtype in enumerate(pat):
            weeks.append(build_week(wtype, cycle_num, start_idx + i))
        return weeks

    if availableWeekNumber >= cycleLength:
        # Full cycle
        full_cycle = pattern_to_weeks(pattern, currentCycleNumber, currentIndexInCycle)
        remaining = availableWeekNumber - cycleLength

        # Recurse for remaining weeks
        next_weeks = getSpecificWeeks(
            remaining,
            load,
            cycleLength,
            nextRestingWeek,
            currentCycleNumber + 1,
            1,
            is_top_level=False,
        )
        weeks = full_cycle + next_weeks

        if is_top_level:
            weeks = fix_ending(weeks, cycleLength)
        return weeks
    else:
        # Partial cycle
        partial = pattern[:availableWeekNumber]

        def ends_in_resting(p):
            return p[-1] == "R"

        if ends_in_resting(partial) and len(partial) > 1:
            # Try alternative partial
            alt_partial = pattern[-availableWeekNumber:]
            if not ends_in_resting(alt_partial):
                partial = alt_partial
            else:
                # Fallback: all worked
                partial = ["W"] * availableWeekNumber

        weeks = pattern_to_weeks(partial, currentCycleNumber, currentIndexInCycle)

        if is_top_level:
            weeks = fix_ending(weeks, cycleLength)

        return weeks

# @st.cache_data
def compute_training_plan(inputs):
    result = []
    total_number_of_hours = 0
    for i in range(len(inputs["races"])):
        log_info(f"Computing training plan for {i} race")
        log_info(f"Inputs: {inputs}")
        if inputs["races"][i]["distance"] >= 0:
            new_weeks = compute_training_plan_1_race(inputs, i)
            for week in new_weeks:
                total_number_of_hours += week["theoreticalWeeklyTSS"]/60
            result = result + new_weeks
    log_info(f"Total number of hours: {total_number_of_hours}")
    st.session_state["total_number_of_hours"] = int(total_number_of_hours)
    return result

# @st.cache_data
def compute_training_plan_1_race(inputs, i):
    raceDistanceKm = inputs["races"][i]["distance"]
    targetTimeInMinutes = (
        inputs["races"][i]["target_minutes"] + inputs["races"][i]["target_hours"] * 60
    )
    mainSport = inputs["races"][i]["sport"]
    objective = inputs["races"][i]["objective"]
    fitnessLevel = inputs["level"]
    if inputs["races"][i]["other_sports"] != []:
        mainSportShare = 1 - sum(inputs["races"][i]["other_sport_shares"].values())
    else:
        mainSportShare = 1
    eventSize = determineEventSize(raceDistanceKm, mainSport)
    raceZone = determineRaceZone(eventSize, objective)
    eventTSS = calculateEventTss(raceZone, mainSport, targetTimeInMinutes)

    raceInfo = {
        "raceDistanceKm": raceDistanceKm,
        "targetTimeInMinutes": targetTimeInMinutes,
        "eventSize": eventSize,
        "raceZone": raceZone,
        "eventTSS": eventTSS,
        "objective": objective,
        "fitnessLevel": fitnessLevel,
        "mainSportShare": mainSportShare,
        "mainSport": mainSport,
    }

    startLoad = inputs["races"][i]["weekly_start_hours"] * 70
    endLoad = inputs["races"][i]["weekly_end_hours"] * 70
    weeklyTssIncreaseRate = (
        0.05
        if inputs["increase"] == "Low"
        else 0.07
        if inputs["increase"] == "Medium"
        else 0.1
    )
    cycleLength = 4 if inputs["recuperation_level"] == "Low" else 3
    if i == 0:
        nextRestingWeek = inputs["next_resting_week"]
    else:
        nextRestingWeek = 0
    declaredHandableLoad = inputs["weekly_hours"] * (
        60 if "intensity_workouts" not in inputs else 60
        if inputs["intensity_workouts"] == 0
        else 65
        if inputs["intensity_workouts"] == 1
        else 70
        if inputs["intensity_workouts"] == 2
        else 75
        if inputs["intensity_workouts"] == 3
        else 80
        if inputs["intensity_workouts"] == 4
        else 85
        if inputs["intensity_workouts"] == 5
        else 90
    )
    declaredNextRestingWeek = inputs["next_resting_week"]
    currentLongRunTss = (
        (inputs["longest_workout_hours"] * 60 + inputs["longest_workout_minutes"])
        / 60
        * 65
    )

    currentLongRaceIntensityTss = 0.2 * eventTSS
    minTssPerWorkout = 30
    maxTssPerWorkout = REGULAR_MAX_WORKOUT_TSS_BY_SPORT_BY_OBJECTIVE_BY_OBJECTIVE_SIZE_BY_ATHLETE_LEVEL[
        raceInfo["mainSport"]
    ][raceInfo["objective"]][raceInfo["eventSize"]][raceInfo["fitnessLevel"]]
    # maxTempoTssInLong = 50
    maxTssPerDay = (
        MAX_TSS_PER_DAY_BY_SPORT_BY_OBJECTIVE_BY_OBJECTIVE_SIZE_BY_ATHLETE_LEVEL[
            raceInfo["mainSport"]
        ][raceInfo["objective"]][raceInfo["eventSize"]][raceInfo["fitnessLevel"]]
    )
    finalLongRunTss = (
        LONG_WORKOUT_TSS_BY_SPORT_BY_OBJECTIVE_BY_OBJECTIVE_SIZE_BY_ATHLETE_LEVEL_PERCENTAGE_OF_RACE[
            raceInfo["mainSport"]
        ][raceInfo["objective"]][raceInfo["eventSize"]][raceInfo["fitnessLevel"]]
        * eventTSS
    )
    finalRaceIntensityTss = (
        RACE_INTENSITY_WORKOUT_TSS_BY_SPORT_BY_OBJECTIVE_BY_OBJECTIVE_SIZE_BY_ATHLETE_LEVEL_PERCENTAGE_OF_RACE[
            raceInfo["mainSport"]
        ][raceInfo["objective"]][raceInfo["eventSize"]][raceInfo["fitnessLevel"]]
        * eventTSS
    )
    finalShortIntensityTss = 50
    finalLongIntensityTss = 70

    loadsInfo = {
        "startLoad": startLoad,
        "endLoad": endLoad,
        "weeklyTssIncreaseRate": weeklyTssIncreaseRate,
        "cycleLength": cycleLength,
        "nextRestingWeek": nextRestingWeek,
        "declaredHandableLoad": declaredHandableLoad,
        "declaredNextRestingWeek": declaredNextRestingWeek,
        "minTssPerWorkout": minTssPerWorkout,
        "maxTssPerWorkout": maxTssPerWorkout,
        # "maxTempoTssInLong": maxTempoTssInLong,
        "maxTssPerDay": maxTssPerDay,
        "currentLongRunTSS": currentLongRunTss,
        "currentRaceIntensityTSS": currentLongRaceIntensityTss,
        "finalLongRunTSS": finalLongRunTss,
        "finalRaceIntensityTSS": finalRaceIntensityTss,
        "finalShortIntensityTSS": finalShortIntensityTss,
        "finalLongIntensityTSS": finalLongIntensityTss,
    }

    raceDate = inputs["races"][i]["date"]
    
    if i > 0:
        # startDate is the next monday after the previous race, between 4 and 11 days after
        lastRaceDate = inputs["races"][i - 1]["date"]

        # startDate = lastRaceDate + timedelta(days=(7 - lastRaceDate.weekday() if lastRaceDate.weekday() >= 4 else 0))
        startDate = lastRaceDate + timedelta(days=(6 - lastRaceDate.weekday()))
        startDate = datetime(startDate.year, startDate.month, startDate.day)
        # currentDate = lastRaceDate + timedelta(days=(7 - lastRaceDate.weekday() if lastRaceDate.weekday() >= 4 else 0))
        currentDate = lastRaceDate + timedelta(days=(6 - lastRaceDate.weekday()))
        # convert currentDate to datetime
        currentDate = datetime(currentDate.year, currentDate.month, currentDate.day)
    else:
        startDate = datetime.today()
        currentDate = datetime.today()
        # currentDate = datetime(year=2024, month=12, day=19)
    
    
    # currentDate = datetime(currentDate.year, currentDate.month, currentDate.day)
    datesInfo = {
        "startDate": startDate,
        "endDate": raceDate,
        "currentDate": currentDate,
        "currentWeekStart": currentDate - timedelta(currentDate.weekday()),
        "currentWeekEnd": currentDate + timedelta(6 - currentDate.weekday()),
        "raceWeekStart": raceDate - timedelta(raceDate.weekday()),
        "raceWeekEnd": raceDate + timedelta(6 - raceDate.weekday()),
        "numberOfWeeks": (
            datetime(year=raceDate.year, month=raceDate.month, day=raceDate.day)
            - timedelta(raceDate.weekday())
            - currentDate
            - timedelta(currentDate.weekday())
        ).days
        // 7,
    }

    longWorkoutDay = inputs["week_organization"]["long_workout_day"]
    availableDays = inputs["week_organization"]["workout_days"]
    dayAvailableDurations = inputs["week_organization"]["workout_durations"]
    # convert the dayAvailableDurations from hours to seconds
    dayAvailableDurations = {
        day: dayAvailableDurations[day] * 60 * 60 for day in dayAvailableDurations
    }
    weekInfo = {
        "longWorkoutDay": longWorkoutDay,
        "availableDays": availableDays,
        "dayAvailableDurations": dayAvailableDurations,
    }

    currentPlannedMacrocycles = []
    currentPlannedMicrocycles = []
    completedWorkouts = []
    totalMacrocycles, totalMicrocycles = planWeekLoads(
        loadsInfo,
        datesInfo,
        raceInfo,
        weekInfo,
        currentPlannedMacrocycles,
        currentPlannedMicrocycles,
        completedWorkouts,
        i
    )
    return totalMicrocycles

def send_to_db(data_cycles, inputs, athlete_id, session_id, connection_parameters, result_queue):
    """
    Function to send data (training plan, inputs, races, and week organization) to the database in a separate thread.
    """
    try:
        log_debug("Starting database sync in thread...")

        # Create the Snowflake session
        session = create_snowflake_session(connection_parameters)
        # Handle microcycles and microcycle days
        start_dates = [cycle["startDate"] for cycle in data_cycles]

        if start_dates:
            placeholders = ", ".join(["?"] * len(start_dates))
            session.sql(
                f"DELETE FROM microcycle_days WHERE strava_id = ? AND start_date IN ({placeholders})",
                [athlete_id] + start_dates
            ).collect()
            session.sql(
                f"DELETE FROM microcycles WHERE strava_id = ? AND start_date IN ({placeholders})",
                [athlete_id] + start_dates
            ).collect()

        # Bulk insert microcycles
        microcycle_values = []
        microcycle_params = []
        for cycle in data_cycles:
            microcycle_values.append("(?, ?, ?, ?, ?, ?)")
            microcycle_params.extend([
                athlete_id, session_id, cycle["startDate"], cycle["endDate"],
                cycle["cycleType"], cycle["theoreticalWeeklyTSS"]
            ])

        if microcycle_values:
            mc_val_str = ", ".join(microcycle_values)
            session.sql(f"""
            INSERT INTO microcycles (strava_id, session_id, start_date, end_date, cycle_type, theoretical_weekly_tss)
            VALUES {mc_val_str}
            """, microcycle_params).collect()

        # Bulk insert microcycle days
        day_values = []
        day_params = []
        for cycle in data_cycles:
            if "dayByDay" in cycle:
                for day, day_activities in cycle["dayByDay"].items():
                    for idx, activity in enumerate(day_activities):
                        for zone, seconds in activity["secondsInZone"].items():
                            day_values.append("(?, ?, ?, ?, ?, ?, ?)")
                            day_params.extend([
                                athlete_id, session_id, cycle["startDate"], day, idx + 1, zone, seconds
                            ])

        if day_values:
            day_val_str = ", ".join(day_values)
            session.sql(f"""
            INSERT INTO microcycle_days (strava_id, session_id, start_date, day, workout_idx, zone, seconds)
            VALUES {day_val_str}
            """, day_params).collect()

        # Flatten inputs for storage
        flattened_inputs = {
            "athlete_id": athlete_id,
            "session_id": session_id,
            "level": inputs["level"],
            "recuperation_level": inputs["recuperation_level"],
            "weekly_hours": inputs["weekly_hours"],
            "intensity_workouts": inputs["intensity_workouts"],
            "longest_workout_hours": inputs["longest_workout_hours"],
            "longest_workout_minutes": inputs["longest_workout_minutes"],
            "next_resting_week": inputs["next_resting_week"],
            "increase": inputs["increase"],
        }

        # Merge inputs into the `inputs` table
        session.sql(f"""
        MERGE INTO inputs AS target
        USING (SELECT ? AS athlete_id, ? AS session_id, ? AS level, ? AS recuperation_level, ? AS weekly_hours, 
                      ? AS intensity_workouts, ? AS longest_workout_hours, ? AS longest_workout_minutes, 
                      ? AS next_resting_week, ? AS increase) AS source
        ON target.athlete_id = source.athlete_id AND target.session_id = source.session_id
        WHEN MATCHED THEN UPDATE SET
            level = source.level,
            recuperation_level = source.recuperation_level,
            weekly_hours = source.weekly_hours,
            intensity_workouts = source.intensity_workouts,
            longest_workout_hours = source.longest_workout_hours,
            longest_workout_minutes = source.longest_workout_minutes,
            next_resting_week = source.next_resting_week,
            increase = source.increase
        WHEN NOT MATCHED THEN INSERT (athlete_id, session_id, level, recuperation_level, weekly_hours, intensity_workouts, 
                                      longest_workout_hours, longest_workout_minutes, next_resting_week, increase)
        VALUES (source.athlete_id, source.session_id, source.level, source.recuperation_level, source.weekly_hours, 
                source.intensity_workouts, source.longest_workout_hours, source.longest_workout_minutes, 
                source.next_resting_week, source.increase)
        """, list(flattened_inputs.values())).collect()

        # Merge races
        for race in inputs["races"]:
            session.sql(f"""
            MERGE INTO races AS target
            USING (
                SELECT ? AS athlete_id, ? AS session_id, ? AS date, ? AS objective, ? AS weekly_start_hours,
                       ? AS sport, ? AS target_hours, ? AS weekly_end_hours, ? AS distance, ? AS target_minutes, 
                       ? AS other_sports
            ) AS source
            ON target.athlete_id = source.athlete_id AND target.session_id = source.session_id AND target.date = source.date
            WHEN MATCHED THEN UPDATE SET
                objective = source.objective,
                weekly_start_hours = source.weekly_start_hours,
                sport = source.sport,
                target_hours = source.target_hours,
                weekly_end_hours = source.weekly_end_hours,
                distance = source.distance,
                target_minutes = source.target_minutes,
                other_sports = source.other_sports
            WHEN NOT MATCHED THEN INSERT (athlete_id, session_id, date, objective, weekly_start_hours, sport, 
                                          target_hours, weekly_end_hours, distance, target_minutes, other_sports)
            VALUES (source.athlete_id, source.session_id, source.date, source.objective, source.weekly_start_hours, 
                    source.sport, source.target_hours, source.weekly_end_hours, source.distance, source.target_minutes, 
                    source.other_sports)
            """, [
                athlete_id, session_id, race["date"], race["objective"],
                race["weekly_start_hours"], race["sport"], race["target_hours"],
                race["weekly_end_hours"], race["distance"], race["target_minutes"],
                json.dumps(race["other_sports"])
            ]).collect()

        # Merge week organization
        week_org = inputs["week_organization"]
        session.sql(f"""
        MERGE INTO week_organization AS target
        USING (
            SELECT ? AS athlete_id, ? AS session_id, ? AS long_workout_day, ? AS workout_days, ? AS workout_durations
        ) AS source
        ON target.athlete_id = source.athlete_id AND target.session_id = source.session_id
        WHEN MATCHED THEN UPDATE SET
            long_workout_day = source.long_workout_day,
            workout_days = source.workout_days,
            workout_durations = source.workout_durations
        WHEN NOT MATCHED THEN INSERT (athlete_id, session_id, long_workout_day, workout_days, workout_durations)
        VALUES (source.athlete_id, source.session_id, source.long_workout_day, source.workout_days, source.workout_durations)
        """, [
            athlete_id, session_id, week_org["long_workout_day"],
            json.dumps(week_org["workout_days"]), json.dumps(week_org["workout_durations"])
        ]).collect()

        # Notify success
        result_queue.put("completed")
        log_debug("Database sync completed successfully.")
    except Exception as e:
        result_queue.put(f"error: {str(e)}")
        log_error(f"Error during database sync: {e}")

# Function to add a new race
def add_race():
    if len(st.session_state["inputs"]["races"]) >= 3:
        st.error("Cannot add more than 3 races")
    else:
        st.session_state["inputs"]["races"].append({
            "date": date(2025, 12, 31),
            "objective": "Finish",
            "weekly_start_hours": 5,
            "sport": "Run",
            "target_hours": 3,
            "weekly_end_hours": 7,
            "distance": 42.195,
            "target_minutes": 15,
            "other_sports": [],
            "other_sport_shares": {},
        })
        update_training_preferences()
    
# Function to remove a race by index
def remove_race(index):
    st.session_state["inputs"]["races"].pop(index)
    update_training_preferences()
    

if "inputs_changed" not in st.session_state:
    st.session_state["inputs_changed"] = True  # Assume inputs changed initially

if "plan" not in st.session_state:
    st.session_state["plan"] = None  # Placeholder for the computed training plan

# Initialize session state for all inputs if not already set
if "inputs" not in st.session_state:
    st.session_state["long_workout_day"] = "Saturday"
    st.session_state["workout_days"] = ["Monday", "Wednesday", "Saturday"]
    st.session_state["workout_durations"] = {
        "Monday": 1.5,
        "Wednesday": 1.0,
        "Saturday": 1.0,
    }
    st.session_state["inputs"] = {
        "level": "Confirmed",
        "recuperation_level": "Low",
        "weekly_hours": 3,
        "intensity_workouts": 1,
        "longest_workout_hours": 1,
        "longest_workout_minutes": 00,
        "next_resting_week": 3,
        # "volume": "Medium",
        "increase": "High",
        # "intensity": "Medium",
        "races": [
            {
                "date": date(2025, 4, 6),
                "objective": "Perf",
                "weekly_start_hours": 3,
                "sport": "Run",
                "target_hours": 1,
                "weekly_end_hours": 9,
                "distance": 21.1,
                "target_minutes": 40,
                "other_sports": ["Bike"],
                "other_sport_shares": {"Bike": 0},
            },
            {
                "date": date(2025, 7, 6),
                "objective": "Finish",
                "weekly_start_hours": 6,
                "sport": "Run",
                "target_hours": 6,
                "weekly_end_hours": 8,
                "distance": 60.0,
                "target_minutes": 00,
                "other_sports": [],
                "other_sport_shares": {},
            },
            {
                "date": date(2025, 11, 16),
                "objective": "Perf",
                "weekly_start_hours": 6,
                "sport": "Run",
                "target_hours": 3,
                "weekly_end_hours": 8,
                "distance": 42.195,
                "target_minutes": 20,
                "other_sports": [],
                "other_sport_shares": {},
            },
        ],
        "week_organization": {
            "long_workout_day": "Sunday",
            "workout_days": ["Tuesday", "Wednesday", "Thursday", "Saturday", "Sunday"],
            "workout_durations": {
                "Tuesday": 2.0,
                "Wednesday": 2.0,
                "Thursday": 2.0,
                "Saturday": 2.0,
                "Sunday": 5.0,
            },
        },
    }


def update_training_preferences():
    # Ensure all input fields are synced to the session state
    result = {
        "level": st.session_state["input_level"],
        "recuperation_level": st.session_state["input_recuperation_level"],
        "weekly_hours": st.session_state["input_weekly_hours"],
        # "intensity_workouts": st.session_state["input_intensity_workouts"],
        "longest_workout_hours": st.session_state["input_longest_workout_hours"],
        "longest_workout_minutes": st.session_state["input_longest_workout_minutes"],
        "next_resting_week": st.session_state["input_next_resting_week"],
        # "volume": st.session_state["input_volume"],
        "increase": st.session_state["input_increase"],
        # "intensity": st.session_state["input_intensity"]
    }
    result["races"] = update_race_data()
    result["week_organization"] = update_week_organization()
    log_debug(f"Updating training preferences: {result}")
    log_debug(f"Session state inputs: {st.session_state['inputs']}")
    st.session_state["inputs"].update(result)
    log_info(f"Updated training preferences: {result}")
    st.session_state["inputs_changed"] = True  # Mark inputs as changed


if st.session_state["inputs_changed"]:
    st.session_state["plan"] = compute_training_plan(st.session_state["inputs"])
    st.session_state["inputs_changed"] = False  # Reset the flag
    # # Trigger recompute
    # st.session_state["mock_data"] = compute_training_plan(st.session_state["inputs"])
    # Launch the background sync thread
    data_cycles = st.session_state["plan"]
    athlete_id = st.session_state.get("athlete_id", "0")
    # session_id = st.session_state.get("cookies", {}).get("session_id", "")

    threading.Thread(
        target=send_to_db,
        args=(data_cycles, st.session_state["inputs"], athlete_id, session_id, connection_parameters, st.session_state["result_queue"]),
        daemon=True,
    ).start()
    st.session_state["db_sync_status"] = "in_progress"


def update_race_data():
    # Dynamically collect all race data
    races = []
    for i, _ in enumerate(st.session_state["inputs"]["races"]):
        race_data = {
            "date": st.session_state[f"race{i}_date"],
            "objective": st.session_state[f"race{i}_objective"],
            "weekly_start_hours": st.session_state[f"race{i}_weekly_start_hours"],
            "sport": st.session_state[f"race{i}_sport"],
            "target_hours": st.session_state[f"race{i}_target_hours"],
            "weekly_end_hours": st.session_state[f"race{i}_weekly_end_hours"],
            "distance": st.session_state[f"race{i}_distance"],
            "target_minutes": st.session_state[f"race{i}_target_minutes"],
            "other_sports": st.session_state[f"other_sports{i}"],
            "other_sport_shares": {
                sport: st.session_state.get(f"other_sport{i}_{sport}_share", 0)
                for sport in st.session_state[f"other_sports{i}"]
            },
        }
        races.append(race_data)
    # order races by date
    races = sorted(races, key=lambda x: x["date"])

    return races


def update_week_organization():
    # Update the week organization in session state
    return {
        "long_workout_day": st.session_state["input_long_workout_day"],
        "workout_days": st.session_state["input_workout_days"],
        "workout_durations": {
            day: st.session_state[f"input_duration_{day}"]
            for day in st.session_state["input_workout_days"]
        },
    }


# Helper function to ensure total share does not exceed 50%
def validate_total_share(shares):
    total_share = sum(shares.values())
    if total_share > 50:
        st.error(
            f"Total share for other sports cannot exceed 50%. Currently: {total_share}%"
        )

# @st.cache_data
def fetch_activities(after_ts):
    activities = []
    page = 1
    while True:
        log_info(f"Fetching activities from page {page}...")
        url = f"https://www.strava.com/api/v3/athlete/activities?after={after_ts}&page={page}&per_page=100"
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            st.error("Failed to fetch activities.")
            break
        batch = response.json()
        log_info(f"Fetched {len(batch)} activities from page {page}")
        if not batch:
            break
        activities.extend(batch)
        page += 1
    return activities

def calculate_training_hours(activities):
    """
    Calculate total training hours from the activities fetched.
    """
    total_seconds = sum(activity.get("moving_time", 0) for activity in activities)
    return total_seconds / 3600  # Convert seconds to hours

def recommend_level(training_hours):
    """
    Recommend a training level based on total hours in the past year.
    """
    if training_hours > 300:
        return "Confirmed"
    elif training_hours > 200:
        return "Intermediate"
    else:
        return "Beginner"

def recommend_weekly_hours(activities):
    """
    Recommend the current weekly training hours based on the past 4 weeks
    """
    last_4_weeks_activities = []
    for activity in activities:
        activity_date = datetime.strptime(activity["start_date"], "%Y-%m-%dT%H:%M:%SZ")
        if activity_date >= datetime.utcnow() - timedelta(weeks=4):
            last_4_weeks_activities.append(activity)
    total_seconds = sum(activity.get("moving_time", 0) for activity in last_4_weeks_activities)
    total_hours = total_seconds / 3600
    return int(total_hours / 4)


def recommend_intensity_workouts(activities):
    """
    Recommend the number of intensity workouts based on the past 4 weeks
    """
    last_4_weeks_activities = []
    for activity in activities:
        activity_date = datetime.strptime(activity["start_date"], "%Y-%m-%dT%H:%M:%SZ")
        if activity_date >= datetime.utcnow() - timedelta(weeks=4):
            last_4_weeks_activities.append(activity)
    intensity_workouts = 0
    for activity in last_4_weeks_activities:
        if activity.get("workout_type") == 3:
            intensity_workouts += 1
    return intensity_workouts

def recommend_longest_workout(activities):
    """
    Recommend the longest workout duration based on the last 4 weeks
    """
    longest_workout_minutes = 0
    for activity in activities:
        activity_date = datetime.strptime(activity["start_date"], "%Y-%m-%dT%H:%M:%SZ")
        if activity_date >= datetime.utcnow() - timedelta(days=28):
            duration = activity.get("moving_time", 0) / 60  # Convert seconds to minutes
            log_info(f"Duration: {duration} of activity: {activity['name']} from date {activity['start_date']}")
            if duration > longest_workout_minutes:
                log_info(f"New longest workout: {duration} minutes for activity: {activity['name']}")
                longest_workout_minutes = duration
    return int(longest_workout_minutes // 60), int(longest_workout_minutes % 60)

def recommend_next_resting_week(activities):
    """
    Recommend the next resting week based on the last 4 weeks, the last resting week was the one with the lowest moving time
    the next should be cycleLength weeks after the last resting week
    """
    activities_by_week = defaultdict(int)
    for activity in activities:
        if datetime.strptime(activity["start_date"], "%Y-%m-%dT%H:%M:%SZ") >= datetime.utcnow() - timedelta(weeks=4):
            activity_week = datetime.strptime(activity["start_date"], "%Y-%m-%dT%H:%M:%SZ").isocalendar()[1]
            activities_by_week[activity_week] += activity.get("moving_time", 0)
    if not activities_by_week:
        return 0
    min_moving_time = min(activities_by_week.values())
    resting_week = [week for week, moving_time in activities_by_week.items() if moving_time == min_moving_time][0]
    next_resting_week = resting_week + 4
    #compared to current week
    current_week = datetime.utcnow().isocalendar()[1]
    return next_resting_week - current_week


# Initialize state variables
if "fetching_complete" not in st.session_state:
    st.session_state["fetching_complete"] = False

if "training_hours" not in st.session_state:
    st.session_state["training_hours"] = None

if "level_recommendation" not in st.session_state:
    st.session_state["level_recommendation"] = None

def fetch_and_recommend(connection_parameters):
    """
    Fetch activities from Strava for the past year and calculate a level recommendation.
    """
    try:
        log_info("Fetching activities for level recommendation...")
        last_year = int((datetime.utcnow() - timedelta(days=365)).timestamp())
        activities = fetch_activities(last_year)
        log_info(f"Fetched {len(activities)} activities.")
        if activities:
            # Build a single MERGE statement with multiple values
            values_clause = ", ".join(["(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"] * len(activities))
            
            params = []
            for activity in activities:
                params.extend([
                    activity["id"],
                    st.session_state["athlete_id"],
                    session_id,
                    activity["name"],
                    activity["start_date"],
                    activity["distance"],
                    activity["moving_time"],
                    activity["elapsed_time"],
                    activity["total_elevation_gain"],
                    activity["type"]
                ])

            query = f"""
            MERGE INTO activities a
            USING (
                SELECT * FROM VALUES {values_clause}
                AS vals(id, athlete_id, session_id, name, start_date, distance, moving_time, elapsed_time, total_elevation_gain, type)
            ) vals
            ON a.id = vals.id
            WHEN NOT MATCHED THEN
                INSERT (id, athlete_id, session_id, name, start_date, distance, moving_time, elapsed_time, total_elevation_gain, type)
                VALUES (vals.id, vals.athlete_id, vals.session_id, vals.name, vals.start_date, vals.distance, vals.moving_time, vals.elapsed_time, vals.total_elevation_gain, vals.type)
            """
            session = create_snowflake_session(connection_parameters)
            session.sql(query, params).collect()
            log_debug(f"Inserted {len(activities)} activities into Snowflake.")

            st.success(f"Downloaded and stored {len(activities)} activities from the last two months.")
        training_hours = calculate_training_hours(activities)
        st.session_state["training_hours"] = training_hours
        st.session_state["level_recommendation"] = recommend_level(training_hours)
        st.session_state["current_weekly_hours_recommendation"] = recommend_weekly_hours(activities)
        st.session_state["current_intensity_workouts_recommendation"] = recommend_intensity_workouts(activities)
        st.session_state["current_longest_workout_hours_recommendation"], st.session_state["current_longest_workout_minutes_recommendation"] = recommend_longest_workout(activities)
        st.session_state["current_next_resting_week_recommendation"] = recommend_next_resting_week(activities)
        
        st.session_state["fetching_complete"] = True  # Mark as complete
        log_info(f"Level recommendation calculated successfully, training hours: {training_hours}, recommendation: {st.session_state['level_recommendation']}, current weekly hours: {st.session_state['current_weekly_hours_recommendation']}, current intensity workouts: {st.session_state['current_intensity_workouts_recommendation']}, current longest workout: {st.session_state['current_longest_workout_hours_recommendation']}:{st.session_state['current_longest_workout_minutes_recommendation']}, current next resting week: {st.session_state['current_next_resting_week_recommendation']}")
        st.rerun()
    except Exception as e:
        st.session_state["fetching_complete"] = True  # Avoid indefinite waiting
        log_error(f"Error during level recommendation: {e}")



def add_columns_if_not_exists(table_name, columns, session):
    """
    Add columns to a Snowflake table if they do not exist.

    Args:
        table_name (str): The name of the table to modify.
        columns (dict): A dictionary of column names and types, e.g., {"column_name": "VARCHAR"}.
        session (snowflake.snowpark.Session): The Snowflake session object.
    """
    # Fetch existing columns
    existing_columns = session.sql(f"DESCRIBE TABLE {table_name}").collect()
    existing_column_names = {row["name"].lower() for row in existing_columns}  # Ensure case-insensitivity

    # Iterate through desired columns and add missing ones
    for column_name, column_type in columns.items():
        if column_name.lower() not in existing_column_names:
            # Add the column if not exists
            session.sql(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}").collect()
            log_debug(f"Added column {column_name} to {table_name}.")
        else:
            log_debug(f"Column {column_name} already exists in {table_name}.")


# 4. Fetch the Last Activity
# @st.cache_data
def get_last_activity(access_token):
    url = f"{STRAVA_API_URL}/athlete/activities"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"per_page": 100, "page": 1}
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        activities = response.json()
        if activities:
            return activities[0]
        else:
            log_debug("No activities found.")
    else:
        log_debug(f"Error fetching last activity: {response.status_code}, {response.text}")
    return None

# 2. Upload Image to Imgur CDN
def upload_image_to_imgur(image_path):
    headers = {"Authorization": f"Client-ID {imgur_client_id}"}
    with open(image_path, "rb") as img_file:
        response = requests.post(
            "https://api.imgur.com/3/image", headers=headers, files={"image": img_file}
        )
    if response.status_code == 200:
        log_debug(f"Image uploaded to Imgur, link: {response.json()['data']['link']}")
        return response.json()["data"]["link"]  # Get the public URL of the uploaded image
    else:
        log_debug(f"Error uploading image to Imgur: {response.status_code}, {response.text}")
        return None
    
# 3. Update Strava Activity Description
def update_activity_description(activity_id, description, access_token):
    url = f"{STRAVA_API_URL}/activities/{activity_id}"
    headers = {"Authorization": f"Bearer {access_token}"}
    data = {"description": description}
    response = requests.put(url, headers=headers, json=data)
    if response.status_code == 200:
        log_debug(f"Description updated successfully, with response: {response.json()}")
    else:
        log_debug(f"Error updating description: {response.status_code}, {response.text}")

def to_unicode_bold_sans(text):
    """Convert text to Unicode Mathematical Sans-Serif Bold."""
    bold_text = ""
    for char in text:
        if 'a' <= char <= 'z':
            bold_text += chr(ord(char) + 0x1D5EE - ord('a'))
        elif 'A' <= char <= 'Z':
            bold_text += chr(ord(char) + 0x1D5D4 - ord('A'))
        elif '0' <= char <= '9':
            bold_text += chr(ord(char) + 0x1D7EC - ord('0'))
        else:
            bold_text += char
    return bold_text

# Check if we have an access token in session_state
if "access_token" not in st.session_state:
    st.session_state["access_token"] = None

# Parse query parameters
params = st.query_params

session = create_snowflake_session(connection_parameters)

# # Updated `inputs` table schema
# session.sql("""
# CREATE TABLE IF NOT EXISTS inputs (
#     athlete_id INTEGER,
#     session_id VARCHAR,
#     level VARCHAR,
#     recuperation_level VARCHAR,
#     weekly_hours FLOAT,
#     intensity_workouts INTEGER,
#     longest_workout_hours INTEGER,
#     longest_workout_minutes INTEGER,
#     next_resting_week INTEGER,
#     increase VARCHAR,
#     PRIMARY KEY (athlete_id, session_id)
# )
# """).collect()

# # Races table schema
# session.sql("""
# CREATE TABLE IF NOT EXISTS races (
#     athlete_id INTEGER,
#     session_id VARCHAR,
#     date DATE,
#     objective VARCHAR,
#     weekly_start_hours FLOAT,
#     sport VARCHAR,
#     target_hours FLOAT,
#     weekly_end_hours FLOAT,
#     distance FLOAT,
#     target_minutes FLOAT,
#     other_sports VARCHAR, -- Changed from JSON to VARCHAR
#     PRIMARY KEY (athlete_id, session_id, date)
# )
# """).collect()

# # Week organization table schema
# session.sql("""
# CREATE TABLE IF NOT EXISTS week_organization (
#     athlete_id INTEGER,
#     session_id VARCHAR,
#     long_workout_day VARCHAR,
#     workout_days VARCHAR, -- Changed from JSON to VARCHAR
#     workout_durations VARCHAR, -- Changed from JSON to VARCHAR
#     PRIMARY KEY (athlete_id, session_id)
# )
# """).collect()


# # Create or alter `activities` table
# session.sql("""
# CREATE TABLE IF NOT EXISTS activities (
#     id INTEGER,
#     athlete_id INTEGER,
#     session_id VARCHAR,
#     name VARCHAR,
#     start_date VARCHAR,
#     distance FLOAT,
#     moving_time INTEGER,
#     elapsed_time INTEGER,
#     total_elevation_gain FLOAT,
#     type VARCHAR,
#     PRIMARY KEY (id)
# )
# """).collect()

# # Example usage
# add_columns_if_not_exists(
#     "activities",
#     {
#         "athlete_id": "INTEGER",
#         "session_id": "VARCHAR",
#         "name": "VARCHAR",
#         "start_date": "VARCHAR",
#         "distance": "FLOAT",
#         "moving_time": "INTEGER",
#         "elapsed_time": "INTEGER",
#         "total_elevation_gain": "FLOAT",
#         "type": "VARCHAR",
#     },
#     session
# )

# # Create or alter `microcycles` table
# session.sql("""
# CREATE TABLE IF NOT EXISTS microcycles (
#     strava_id INTEGER,
#     session_id VARCHAR,
#     start_date VARCHAR,
#     end_date VARCHAR,
#     cycle_type VARCHAR,
#     theoretical_weekly_tss FLOAT,
#     PRIMARY KEY (strava_id, start_date)
# )
# """).collect()
# add_columns_if_not_exists(
#     "microcycles",
#     {
#         "session_id": "VARCHAR",
#         "start_date": "VARCHAR",
#         "end_date": "VARCHAR",
#         "cycle_type": "VARCHAR",
#         "theoretical_weekly_tss": "FLOAT",
#     },
#     session
# )

# # Create or alter `microcycle_days` table
# session.sql("""
# CREATE TABLE IF NOT EXISTS microcycle_days (
#     strava_id INTEGER,
#     session_id VARCHAR,
#     start_date VARCHAR,
#     day VARCHAR,
#     workout_idx INTEGER,
#     zone VARCHAR,
#     seconds INTEGER,
#     PRIMARY KEY (strava_id, start_date, day, workout_idx, zone)
# )
# """).collect()

# add_columns_if_not_exists(
#     "microcycle_days",
#     {
#         "session_id": "VARCHAR",
#         "start_date": "VARCHAR",
#         "day": "VARCHAR",
#         "workout_idx": "INTEGER",
#         "zone": "VARCHAR",
#         "seconds": "INTEGER",
#     },
#     session
# )

# If we have a code from Strava, attempt to exchange it for a token
if "code" in params and st.session_state["access_token"] is None:
    code = params["code"]  # Direct access to the correct key-value pair

    # Exchange authorization code for access token
    token_url = "https://www.strava.com/oauth/token"
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
    }
    response = requests.post(token_url, data=data)
    log_info(f"Exchanging code for token: {response.json()}")

    if response.status_code == 200:
        token_data = response.json()
        st.session_state["access_token"] = token_data["access_token"]
        # Assume you have athlete_id from the token_data after login
        athlete_id = token_data["athlete"]["id"]
        st.session_state["athlete_id"] = athlete_id
    else:
        st.error("Failed to exchange code for token. Check your credentials and redirect URI.")
        st.stop()


if st.session_state["access_token"] is not None:
    log_info("No code found in query parameters.")
    log_info(f"Cookies ready: {cookies.ready()}, session_id in cookies: {'session_id' in cookies}, access token set: {st.session_state['access_token'] is not None}")
    if cookies.ready() and "session_id" in cookies and st.session_state["access_token"] is not None:
        log_info("Session ID found in cookies and access token is set.")
        # We have a token. We can call Strava's API.
        # st.write("You are logged in!")

        # Fetch activities from Strava
        access_token = st.session_state["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}
        now = datetime.utcnow()
        two_months_ago = now - timedelta(days=60)
        after_timestamp = int(two_months_ago.timestamp())
        
        # Launch the background fetch for activities if not already done
        log_info("Checking if background fetch is needed...")
        log_info(f"fetched_activities: {st.session_state.get('fetched_activities')}, access_token: {st.session_state.get('access_token', False)}, fetching_complete: {st.session_state.get('fetching_complete')}, fetched activity is present: {'fetched_activities' in st.session_state}, fetching activities: {'fetching_activities' in st.session_state}, fetching complete in session state: {'fetching_complete' in st.session_state}")
        if ("fetching_activities" not in st.session_state or not st.session_state["fetching_activities"]) and "access_token" in st.session_state and st.session_state["access_token"] and not st.session_state["fetching_complete"]:
            log_info("Starting background fetch for activities...")
            st.session_state["fetching_activities"] = True
            ctx = get_script_run_ctx()
            thread = threading.Thread(target=fetch_and_recommend, args=(connection_parameters,), daemon=True)
            log_info(f"Thread started: {thread}")
            add_script_run_ctx(thread,ctx)
            thread.start()


        # activities = fetch_activities(after_timestamp)

        # if activities:
        #     # Build a single MERGE statement with multiple values
        #     values_clause = ", ".join(["(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"] * len(activities))
            
        #     params = []
        #     for activity in activities:
        #         params.extend([
        #             activity["id"],
        #             st.session_state["athlete_id"],
        #             session_id,
        #             activity["name"],
        #             activity["start_date"],
        #             activity["distance"],
        #             activity["moving_time"],
        #             activity["elapsed_time"],
        #             activity["total_elevation_gain"],
        #             activity["type"]
        #         ])

        #     query = f"""
        #     MERGE INTO activities a
        #     USING (
        #         SELECT * FROM VALUES {values_clause}
        #         AS vals(id, athlete_id, session_id, name, start_date, distance, moving_time, elapsed_time, total_elevation_gain, type)
        #     ) vals
        #     ON a.id = vals.id
        #     WHEN NOT MATCHED THEN
        #         INSERT (id, athlete_id, session_id, name, start_date, distance, moving_time, elapsed_time, total_elevation_gain, type)
        #         VALUES (vals.id, vals.athlete_id, vals.session_id, vals.name, vals.start_date, vals.distance, vals.moving_time, vals.elapsed_time, vals.total_elevation_gain, vals.type)
        #     """
        #     session = create_snowflake_session(connection_parameters)
        #     session.sql(query, params).collect()
        #     log_debug(f"Inserted {len(activities)} activities into Snowflake.")

            # st.success(f"Downloaded and stored {len(activities)} activities from the last two months.")

# First Row: My Level Fields
st.header("Training Level and Preferences")
with st.container():
    # Use columns for row layout
    col1, col2 = st.columns([1, 8])  # Adjust column width ratios as needed

    # Column 1: Subheader
    with col1:
        st.subheader("My Level")

    # Column 2: Markdown Link
    with col2:
        if st.session_state["access_token"] is None:
            authorize_url = (
                f"https://www.strava.com/oauth/authorize"
                f"?client_id={client_id}"
                f"&redirect_uri={redirect_uri}"
                f"&response_type=code"
                f"&scope={scopes}"
            )
            st.markdown(f"[Click here to login with Strava to help us assess your level]({authorize_url})", unsafe_allow_html=True) 
    col1, col2, col3, col4, col5, col6, col7 = st.columns(7)

    with col1:
        level = st.selectbox(
            "Level*",
            ["Confirmed", "Intermediate", "Beginner"],
            ["Confirmed", "Intermediate", "Beginner"].index(
                st.session_state["inputs"]["level"]
            ),
            key="input_level",
            on_change=update_training_preferences,
        )
        # Show recommendation if fetching is complete
        if st.session_state["access_token"] is None:
            st.warning("Login with Strava to get recommendation.")
        else:
            if st.session_state["fetching_complete"]:
                if st.session_state["training_hours"] is not None:
                    st.write(
                        f"**Recommended Level:** {st.session_state['level_recommendation']} "
                        f"(Based on {st.session_state['training_hours']:.0f} hours in the past year)"
                    )
                    # if st.button("Update to Recommended Level", key="update_level"):
                    #     st.session_state["input_level"] = st.session_state["level_recommendation"]
                    #     update_training_preferences()
                else:
                    st.error("Failed to fetch activities or calculate training hours.")
            else:
                st.write("Fetching activities... Please wait.")
    

    with col2:
        weekly_hours = st.slider(
            "Current Weekly Hours*",
            1,
            20,
            st.session_state["inputs"]["weekly_hours"],
            key="input_weekly_hours",
            on_change=update_training_preferences,
        )
        # Show recommendation if fetching is complete
        if st.session_state["access_token"] is None:
            st.warning("Login with Strava to get recommendation.")
        else:
            if st.session_state["fetching_complete"]:
                if st.session_state["current_weekly_hours_recommendation"] is not None:
                    st.write(
                        f"**Recommended Weekly Hours:** {st.session_state['current_weekly_hours_recommendation']} "
                    )
                    # if st.button("Update to Recommended weekly hours", key="update_weekly_hours"):
                    #     st.session_state["input_weekly_hours"] = st.session_state["current_weekly_hours_recommendation"]
                    #     update_training_preferences()
                else:
                    st.error("Failed to fetch activities or calculate training hours.")
            else:
                st.write("Fetching activities... Please wait.")
    # with col4:
    #     intensity_workouts = st.selectbox(
    #         "Intensity Workouts*",
    #         list(range(0, 6)),
    #         st.session_state["inputs"]["intensity_workouts"],
    #         key="input_intensity_workouts",
    #         on_change=update_training_preferences,
    #     )

    with col3:
        longest_workout_hours = st.number_input(
            "Longest Workout (hours)*",
            value=st.session_state["inputs"]["longest_workout_hours"],
            step=1,
            key="input_longest_workout_hours",
            on_change=update_training_preferences,
        )
        # Show recommendation if fetching is complete
        if st.session_state["access_token"] is None:
            st.warning("Login with Strava to get recommendation.")
        else:
            if st.session_state["fetching_complete"]:
                if st.session_state["current_longest_workout_hours_recommendation"] is not None:
                    st.write(
                        f"**Recommended Biggest workout:** {st.session_state['current_longest_workout_hours_recommendation']}:{st.session_state['current_longest_workout_minutes_recommendation']} "
                    )
                    # if st.button("Update to Recommended biggest workout"):
                    #     st.session_state["input_longest_workout_hours"] = st.session_state["current_longest_workout_hours_recommendation"]
                    #     st.session_state["input_longest_workout_minutes"] = st.session_state["current_longest_workout_minutes_recommendation"]
                    #     update_training_preferences()
                else:
                    st.error("Failed to fetch activities or calculate training hours.")
            else:
                st.write("Fetching activities... Please wait.")
    with col4:
        longest_workout_minutes = st.number_input(
            "Longest Workout (minutes)*",
            value=st.session_state["inputs"]["longest_workout_minutes"],
            step=1,
            key="input_longest_workout_minutes",
            on_change=update_training_preferences,
        )

    with col5:
        next_resting_week = st.number_input(
            "Next Resting Week",
            value=st.session_state["inputs"]["next_resting_week"],
            step=1,
            key="input_next_resting_week",
            on_change=update_training_preferences,
        )
        # Show recommendation if fetching is complete
        if st.session_state["access_token"] is None:
            st.warning("Login with Strava to get recommendation.")
        else:
            if st.session_state["fetching_complete"]:
                if st.session_state["current_next_resting_week_recommendation"] is not None:
                    st.write(
                        f"**Recommended next resting week:** {st.session_state['current_next_resting_week_recommendation']} "
                    )
                    # if st.button("Update to Recommended next resting week"):
                    #     st.session_state["input_next_resting_week"] = st.session_state["current_next_resting_week_recommendation"]
                    #     update_training_preferences()
                else:
                    st.error("Failed to fetch activities or calculate training hours.")
            else:
                st.write("Fetching activities... Please wait.")
    # with col8:
    #     volume = st.selectbox("Volume", ["Low", "Medium", "High"], ["Low", "Medium", "High"].index(st.session_state["inputs"]["volume"]), key="input_volume",on_change=update_training_preferences)
    with col6:
        recuperation_level = st.selectbox(
            "Recuperation Needs",
            ["Low", "High"],
            ["Low", "High"].index(st.session_state["inputs"]["recuperation_level"]),
            key="input_recuperation_level",
            on_change=update_training_preferences,
        )
        cycle_length = 3 if recuperation_level == "Low" else 4
    with col7:
        increase = st.selectbox(
            "Increase Rate",
            ["Low", "Medium", "High"],
            ["Low", "Medium", "High"].index(st.session_state["inputs"]["increase"]),
            key="input_increase",
            on_change=update_training_preferences,
        )
    # with col10:
    #     intensity = st.selectbox("Intensity", ["Low", "Medium", "High"], ["Low", "Medium", "High"].index(st.session_state["inputs"]["intensity"]), key="input_intensity",on_change=update_training_preferences)
# Second Row: Three Columns for Races


col1, col2, col3 = st.columns([3, 10, 2])
with col1:
    st.header("Race Planning")
with col3:
    st.button("Add Race", on_click=add_race)
# Create dynamic columns based on the number of races
columns = st.columns(min(len(st.session_state["inputs"]["races"]), 3))  # Limit to 3 columns at a time

for i, race in enumerate(st.session_state["inputs"]["races"]):
    with columns[i]:
        col1, col2 = st.columns([1, 1])
        with col1:
            st.subheader(f"Race {i + 1}") 
        with col2:
            st.button(f"Remove Race {i + 1}", on_click=remove_race, args=(i,))
        col1, col2, col3 = st.columns(3)
        
        with col1:
            race_date = st.date_input(
                "Race Date",
                value=st.session_state["inputs"]["races"][i]["date"],
                key=f"race{i}_date",
                on_change=update_training_preferences,
            )
            objective = st.selectbox(
                "Objective",
                ["Perf", "Finish"],
                ["Perf", "Finish"].index(
                    st.session_state["inputs"]["races"][i]["objective"]
                ),
                key=f"race{i}_objective",
                on_change=update_training_preferences,
            )
            weekly_start_hours = st.slider(
                "Weekly Hours (Start of Preparation)",
                1,
                20,
                st.session_state["inputs"]["races"][i]["weekly_start_hours"],
                key=f"race{i}_weekly_start_hours",
                on_change=update_training_preferences,
            )
        with col2:
            sport = st.selectbox(
                "Sport",
                ["Run", "Bike"],
                ["Run", "Bike"].index(st.session_state["inputs"]["races"][i]["sport"]),
                key=f"race{i}_sport",
                on_change=update_training_preferences,
            )
            target_hours = st.number_input(
                "Target Time (hours)",
                value=st.session_state["inputs"]["races"][i]["target_hours"],
                step=1,
                key=f"race{i}_target_hours",
                on_change=update_training_preferences,
            )
            weekly_end_hours = st.slider(
                "Weekly Hours (End of Preparation)",
                1,
                20,
                st.session_state["inputs"]["races"][i]["weekly_end_hours"],
                key=f"race{i}_weekly_end_hours",
                on_change=update_training_preferences,
            )
        with col3:
            distance = st.number_input(
                "Distance (km)",
                value=st.session_state["inputs"]["races"][i]["distance"],
                step=1.0,
                key=f"race{i}_distance",
                on_change=update_training_preferences,
            )
            target_minutes = st.number_input(
                "Target Time (minutes)",
                value=st.session_state["inputs"]["races"][i]["target_minutes"],
                step=1,
                key=f"race{i}_target_minutes",
                on_change=update_training_preferences,
            )
            other_sports = st.multiselect(
                "Other Sports",
                ["Bike"] if sport == "Run" else ["Run"],
                key=f"other_sports{i}",
                on_change=update_training_preferences,
            )
            other_sport_shares = {}
            for other_sport in other_sports:
                other_sport_shares[other_sport] = st.slider(
                    f"{other_sport} Share (%)",
                    min_value=0,
                    max_value=50,
                    value=0,
                    key=f"other_sport{i}_{other_sport}_share",
                    on_change=update_training_preferences,
                )
            validate_total_share(other_sport_shares)

# Mock data for visualization
# data_cycles = compute_training_plan(st.session_state["inputs"])
if "plan" in st.session_state and st.session_state["plan"] is not None:
    data_cycles = st.session_state["plan"]
else:
    data_cycles = compute_training_plan(st.session_state["inputs"])
df_cycles = pd.DataFrame(data_cycles)
if "timeInZoneRepartition" in df_cycles.columns:
    df_cycles["timeInZoneRepartition"] = df_cycles["timeInZoneRepartition"].apply(
        lambda d: {str(k): v for k, v in d.items()} if isinstance(d, dict) else d
    )
df_cycles["startDate"] = pd.to_datetime(df_cycles["startDate"])
df_cycles["endDate"] = pd.to_datetime(df_cycles["endDate"])

if "total_number_of_hours" in st.session_state and "training_hours" in st.session_state and st.session_state["training_hours"] is not None and st.session_state["total_number_of_hours"] is not None:
    st.write(
        f"**Total number of hours in your training plan:** {int(st.session_state['total_number_of_hours'])} meaning around {st.session_state['total_number_of_hours']/len(data_cycles):.1f} hours per week.\n**Last year** you trained {int(st.session_state['training_hours'])} hours, meaning {st.session_state['training_hours']/52:.1f} hours per week."
    )
    increase = ((st.session_state["total_number_of_hours"] / len(data_cycles)) - (st.session_state["training_hours"] / 52))/(st.session_state["training_hours"] / 52)
    if increase > 0.1:
        st.warning(f"**It means an increase of {increase:.1%} compared to last year and it could be too much.**")
    elif increase > 0:
        st.info(f"**It means an increase of {increase:.1%} compared to last year.**")
    else:
        st.success(f"**It means a decrease of {-increase:.1%} compared to last year.**")
    

# Full Row: Training Load Visualization
st.header("Training Load and Week Organization")



# Define all days of the week
WEEK_DAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

# Normalize dayByDay data for visualization, allowing multiple workouts per day
normalized_data = []
log_debug(f"Data cycles {df_cycles.to_string()}")


for cycle in data_cycles:
    start_date = cycle["startDate"]
    end_date = cycle["endDate"]
    if "dayByDay" in cycle:
        for day, activities in cycle["dayByDay"].items():
            for idx, activity in enumerate(activities):
                for zone, seconds in activity["secondsInZone"].items():
                    normalized_data.append(
                        {
                            "startDate": start_date,
                            "endDate": end_date,
                            "Day": day,
                            # Include workout index in Activity to differentiate multiple workouts on the same day
                            "WorkoutIdx": idx + 1,
                            "Zone": str(zone),
                            "Seconds": max(0,int(seconds)),
                            "TimeFormatted": seconds_to_hhmmss(max(0,int(seconds))),
                        }
                    )

activity_df = pd.DataFrame(normalized_data)
log_debug("Activity df")
log_debug(activity_df)

# Convert startDate to date format if present
if "startDate" in activity_df.columns:
    activity_df["startDate"] = pd.to_datetime(activity_df["startDate"]).dt.date
if "endDate" in activity_df.columns:
    activity_df["endDate"] = pd.to_datetime(activity_df["endDate"]).dt.date

# Drop dayByDay if present in df_cycles
if "dayByDay" in df_cycles.columns:
    df_cycles = df_cycles.drop(columns=["dayByDay"])

# Ensure all days and zones are included
WEEK_DAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

full_week_data = pd.DataFrame({"Day": WEEK_DAYS})
activity_df = full_week_data.merge(activity_df, on="Day", how="left").fillna(
    {"Activity": "None", "Zone": "0", "Seconds": 0}
)

# Add a categorical type for proper day ordering
activity_df["Day"] = pd.Categorical(
    activity_df["Day"], categories=WEEK_DAYS, ordered=True
)

# Log final DataFrame
log_debug(f"Final activity_df: {activity_df.to_string()}")

# Periodically check the result of the background task
if st.session_state["db_sync_status"] == "in_progress":
    if not st.session_state["result_queue"].empty():
        result = st.session_state["result_queue"].get()
        if result == "completed":
            st.session_state["db_sync_status"] = "completed"
        elif result.startswith("error"):
            st.session_state["db_sync_status"] = "error"
            st.error(f"An error occurred during sync: {result.split(':', 1)[1]}")

# # Display sync status in the UI
# if st.session_state["db_sync_status"] == "in_progress":
#     st.info("Syncing data in the background...")
# elif st.session_state["db_sync_status"] == "completed":
#     st.success("Data sync completed!")
# elif st.session_state["db_sync_status"] == "error":
#     st.error("An error occurred during the sync.")

# Combine Long Workout TSS and Weekly TSS in the graph
graph_row = st.container()
with graph_row:
    if "dayByDay" in df_cycles.columns:
        df_cycles = df_cycles.drop(columns=["dayByDay"])
    # Define colors for different cycle types
    cycle_colors = {
        "Fondamental": "#1f77b4",  # Blue
        "Specific": "#ff7f0e",     # Orange
        "Pre-Compet": "#2ca02c",  # Green
        "Compet": "#d62728",      # Red
    }

    # Here we use x and x2 for horizontal dimension, and y & y2 for vertical dimension.
    chart_spec = {
        "width": 900,
        "height": 400,
        "data": {"values": df_cycles.to_dict(orient="records")},
        "mark": "bar",
        "encoding": {
            # Horizontal span from startDate to endDate
            "x": {
                "field": "startDate",
                "type": "temporal",
                "title": "Start Date"
            },
            "x2": {"field": "endDate"},
            
            # Vertical extent from 0 to theoreticalWeeklyTSS
            "y": {
                "field": "theoreticalWeeklyTSS",
                "type": "quantitative",
                "title": "Theoretical Weekly TSS",
                "scale": {"domain": [0, 800]}
            },
            "y2": {"value": 0},

            "color": {
                "field": "cycleType",
                "type": "nominal",
                "title": "Cycle Type",
                "scale": {
                    "domain": list(cycle_colors.keys()),
                    "range": list(cycle_colors.values())
                }
            },
            "tooltip": [
                {
                    "field": "theoreticalWeeklyTSS",
                    "type": "quantitative",
                    "title": "Weekly TSS"
                },
                {"field": "cycleType", "type": "nominal", "title": "Cycle Type"}
            ]
        },
        "params": [
            {
                "name": "selector",
                "select": "point"
            }
        ],
        "config": {
            "view": {"strokeOpacity": 0},
            "axis": {"labelFontSize": 12, "titleFontSize": 14}
        }
    }

    event = st.vega_lite_chart(
        chart_spec,
        on_select="rerun",
        use_container_width=True
    )
    
    log_debug(f"Event: {event}")
    
    
    
    # Step 4: Main Execution - Update Last Strava Activity with the Image
    if "access_token" in st.session_state and st.session_state["access_token"]:
        # Create a figure and axis
        fig, ax = plt.subplots(figsize=(12, 6))

        # Plot bars for each cycle
        for _, row in df_cycles.iterrows():
            ax.barh(
                y=0,  # All bars are on the same y-axis for a horizontal span
                left=row["startDate"],
                width=(row["endDate"] - row["startDate"]).days,
                height=row["theoreticalWeeklyTSS"] / 800,  # Normalize height (max TSS = 800)
                color=cycle_colors.get(row["cycleType"], "#cccccc"),
                edgecolor="black",
                label=row["cycleType"] if row["cycleType"] not in ax.get_legend_handles_labels()[1] else ""
            )

        # Beautify the X-axis (dates)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))  # Weekly ticks
        plt.xticks(rotation=45)

        # Add labels and title
        ax.set_title("Training Load and Week Organization")
        ax.set_xlabel("Date")
        ax.set_ylabel("Normalized Weekly TSS (0 to 800)")
        ax.set_ylim(0, 1)  # Normalize height between 0 and 1

        # Add custom legend
        patches = [mpatches.Patch(color=color, label=label) for label, color in cycle_colors.items()]
        ax.legend(handles=patches, title="Cycle Type")

        # Remove y-ticks (cosmetic)
        ax.set_yticks([])

        # Save the graph as an image
        plt.tight_layout()
        plt.savefig("training_load_graph.png", dpi=300)
        log_debug("Access token found. Proceeding to update Strava activity...")
        access_token = st.session_state["access_token"]

        # Path to the image generated earlier
        image_path = "training_load_graph.png"

        if os.path.exists(image_path):
            image_url = upload_image_to_imgur(image_path)
            if not image_url:
                log_debug("Failed to upload image. Exiting.")
            last_activity = get_last_activity(access_token)
            if not last_activity:
                log_debug("Failed to fetch last activity. Exiting.")
            
            if "description" in last_activity:
                old_description = last_activity["description"] 
            else:
                old_description = ""
                
            # Prepare training plan details
            race_distance = f"{st.session_state['inputs']['races'][0]['distance']} km".replace(".", ". ")
            race_sport = f"{st.session_state['inputs']['races'][0]['sport'].capitalize()}"
            race_date = f"{st.session_state['inputs']['races'][0]['date'].strftime('%Y-%m-%d')}"
            week_start_date = f"{df_cycles['startDate'].iloc[0].strftime('%Y-%m-%d')}"
            week_end_date = f"{df_cycles['endDate'].iloc[0].strftime('%Y-%m-%d')}"
            cycle_type = f"{df_cycles['cycleType'].iloc[0]}"
            planned_hours = f"{df_cycles['theoreticalWeeklyTSS'].iloc[0] / 60:.1f}".replace(".", ". ")
            resting = f"{df_cycles['theoreticalResting'].iloc[0]}"

            next_week_cycle_type = f"{df_cycles['cycleType'].iloc[1]}"
            next_week_planned_hours = f"{df_cycles['theoreticalWeeklyTSS'].iloc[1] / 60:.1f}".replace(".", ". ")
            next_week_resting = f"{df_cycles['theoreticalResting'].iloc[1]}"
            
            disguised_url = image_url.replace(".", ". ").replace("://", ":// ")
            

            # Updated description with Unicode bold
            description = (
                f"🏋️ {to_unicode_bold_sans('Training Plan by RaceRoadmap')} 🏋️\n"
                f"🏁 {to_unicode_bold_sans(f'Goal : {race_distance} {race_sport}')} on {to_unicode_bold_sans(race_date)}.\n\n"
                f"({to_unicode_bold_sans('Try it now 👉 type ')}https :// raceroadmap. streamlit. app {to_unicode_bold_sans('without spaces')})\n\n"
                f"📆 Week {week_start_date} to {week_end_date} - {to_unicode_bold_sans(f'{cycle_type} week')} "
                f"(📈 {to_unicode_bold_sans(f'{planned_hours} hours planned for end of the week')} "
                f"({'🛌 Resting week' if resting =='True' else '💪 Working week'}))\n\n"
                f"🔜 {to_unicode_bold_sans('Next week')} will be a {to_unicode_bold_sans(f'{next_week_cycle_type} week')} "
                f"({'🛌 Resting week' if next_week_resting =='True' else '💪 Working week'}) with "
                f"📈 {to_unicode_bold_sans(f'{next_week_planned_hours} hours planned')}.\n\n"
                f"🖼️ Link to yearly training plan: {disguised_url} (remove spaces, thanks Strava)\n\n"
            ) + old_description

            update_activity_description(last_activity["id"], description, access_token)
    else:
        log_debug("Strava Access Token not available. Please log in.")

    # Extract the selected week from event
    if event and "selection" in event and "selector" in event["selection"]:
        log_debug(f"Event: {event}")
        selected_points = event["selection"]["selector"]
        if selected_points:
            # Extract endDate and convert from timestamp to datetime
            selected_week_timestamp = selected_points[0].get("endDate")
            if selected_week_timestamp is not None:
                selected_week_datetime = pd.to_datetime(selected_week_timestamp, unit="ms")
                st.session_state["selected_week"] = selected_week_datetime
                log_debug(f"Selected week: {selected_week_datetime}")
            else:
                st.session_state.pop("selected_week", None)
                log_debug("No week selected pop1.")
        else:
            st.session_state.pop("selected_week", None)
            log_debug("No week selected pop2.")
    else:
        st.session_state.pop("selected_week", None)
        log_debug("No week selected pop3.")

# Week Organization and Activity Visualization
row_organization = st.columns([1, 2])

# Column 1: Week Organization
with row_organization[0]:
    st.subheader("Week Organization")
    long_workout_day = st.selectbox(
        "Day of Long Workout",
        ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ].index(st.session_state["inputs"]["week_organization"]["long_workout_day"]),
        key="input_long_workout_day",
        on_change=update_training_preferences,
    )
    workout_days = st.multiselect(
        "Days I Can Workout",
        ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        default=st.session_state["inputs"]["week_organization"]["workout_days"],
        key="input_workout_days",
        on_change=update_training_preferences,
    )
    workout_durations = {}
    for day in workout_days:
        workout_durations[day] = st.number_input(
            f"Duration on {day} (hours)",
            min_value=0.0,
            max_value=5.0,
            step=0.5,
            value=st.session_state["inputs"]["week_organization"]["workout_durations"][
                day
            ],
            key=f"input_duration_{day}",
            on_change=update_training_preferences,
        )
        


with row_organization[1]:
    st.subheader("Day-by-Day Activity")

    if "selected_week" in st.session_state and st.session_state["selected_week"]:
        selected_week = st.session_state["selected_week"]

        # Filter and merge data
        filtered_activity_df = activity_df[
            activity_df["endDate"] == selected_week.date() + timedelta(days=1)
        ]

        filtered_activity_df = full_week_data.merge(
            filtered_activity_df, on="Day", how="left"
        ).fillna({"WorkoutIdx": 0, "Zone": "0", "Seconds": 0})

        # Set Day as categorical
        filtered_activity_df["Day"] = pd.Categorical(
            filtered_activity_df["Day"], categories=WEEK_DAYS, ordered=True
        )
        log_debug(f"Filtered activity df: {filtered_activity_df.to_string()}")

        if not filtered_activity_df.empty:
            # Generate tick values and labels
            max_seconds = (
                filtered_activity_df.groupby(["Day", "WorkoutIdx"], observed=True)["Seconds"]
                .sum()
                .max()
            )
            y_ticks = format_y_ticks(max_seconds)  # {0: '0:00:00', 816: '0:13:36', ...}

            # Convert ticks to Vega-Lite compatible scale
            y_domain = list(y_ticks.keys())  # Tick values
            y_range = list(y_ticks.values())  # Formatted labels
            
            log_debug(f"Y ticks: {y_ticks}, Y domain: {y_domain}, Y range: {y_range}, max_seconds: {max_seconds}")

            # Modify the chart to use domain and range for custom Y-axis labels
            label_expr = "{ " + ", ".join([f"{k}: '{v}'" for k, v in y_ticks.items()]) + " }[datum.value] || ''"
            
            # Check for multiple workouts per day
            max_workout_idx = filtered_activity_df["WorkoutIdx"].max()
            x_offset = (
                {"field": "WorkoutIdx", "type": "ordinal"}
                if max_workout_idx > 1
                else None
            )

            # Create the Vega-Lite chart_spec
            chart_spec = {
                "width": 800,
                "height": 400,
                "data": {"values": filtered_activity_df.to_dict(orient="records")},
                "mark": {"type": "bar"},
                "encoding": {
                    "x": {
                        "field": "Day",
                        "type": "ordinal",
                        "title": "Day",
                        "sort": WEEK_DAYS
                    },
                    "y": {
                        "field": "Seconds",
                        "type": "quantitative",
                        "title": "Time",
                        "axis": {
                            "title": "Time",
                            "values": y_domain,
                            "labelExpr": label_expr
                        }
                    },
                    "color": {
                        "field": "Zone",
                        "type": "quantitative",
                        "scale": {
                            "domain": [1, 7],
                            "range": ["#ADD8E6", "#FF0000"]
                        },
                        "legend": {"title": "Zones"}
                    },
                    "tooltip": [
                        {"field": "Zone", "type": "nominal", "title": "Zone"},
                        {"field": "TimeFormatted", "type": "nominal", "title": "Time"},
                        {"field": "WorkoutIdx", "type": "ordinal", "title": "Workout"}
                    ],
                    "opacity": {
                        "condition": {
                            "param": "select_workout",
                            "value": 1
                        },
                        "value": 0.4
                    }
                },
                "params": [
                    {
                        "name": "select_workout",
                        "select": {
                            "type": "point",
                            "fields": ["Day", "WorkoutIdx"]
                        }
                    }
                ]
            }

            # Conditionally add xOffset if more than 1 WorkoutIdx exists
            if x_offset:
                chart_spec["encoding"]["xOffset"] = x_offset
            # Render the Vega-Lite chart and capture selection
            event2 = st.vega_lite_chart(
                chart_spec,
                on_select="rerun",
                use_container_width=True
            )

            # Extract the selected point and update session_state
            if event2 and "selection" in event2:
                selected_data = event2["selection"]["select_workout"]
                log_debug(f"Selected data: {selected_data}")
                if selected_data:
                    selected_point = selected_data[0]  # Take the first selected point
                    selected_day = selected_point.get("Day")
                    selected_workout = selected_point.get("WorkoutIdx")
                    if selected_day and selected_workout:
                        st.session_state["selected_day"] = selected_day
                        st.session_state["selected_workout"] = selected_workout
                        log_debug(f"Selected Day: {selected_day}, WorkoutIdx: {selected_workout}")
        else:
            st.write("No activity data found for the selected week.")
    else:
        st.write("No week selected. Waiting for user interaction.")
        
        

    log_debug(f"Dump session state keys: {st.session_state.keys()}")
    if (
        "selected_week" in st.session_state
        and st.session_state["selected_week"]
        and "selected_day" in st.session_state
        and "selected_workout" in st.session_state
    ):
        selected_week = st.session_state["selected_week"].to_pydatetime()+ timedelta(days=1)  # Convert to date
        log_debug(f"Selected week: {selected_week} and type {type(selected_week)}")
        
        week = None
        log_debug(f"Data cycles: {data_cycles}")
        for microcycle in data_cycles:
            # Normalize endDate for comparison
            log_debug(f"Microcycle endDate: {microcycle['endDate']} and type {type(microcycle['endDate'])}")
            if isinstance(microcycle["endDate"], datetime):
                microcycle["endDate"] = microcycle["endDate"].date()
            if microcycle["endDate"] == selected_week.date():
                week = microcycle
                break

        if week:
            log_debug(f"Selected week: {week}")  # Remove .to_string()
            selected_workout = st.session_state["selected_workout"]
            log_debug(f"Selected workout: {selected_workout}")
            selected_day = st.session_state["selected_day"]
            log_debug(f"Selected day: {selected_day}")

            # Fetch the activity details
            activity = week["dayByDay"][selected_day][selected_workout - 1]
            log_debug(f"Activity: {activity}")
            # Extract and build timeline data
            if "intervalSuggestions" in activity:
                # Extract and build timeline data
                intervals = activity["intervalSuggestions"]

                # Initialize variables for accumulated time
                timeline_data = []
                current_time = 0

                # Loop through intervals to accumulate time
                for interval in intervals:
                    for zone, seconds in interval["secondsInZone"].items():
                        timeline_data.append({
                            "start_time_timeline": current_time,
                            "end_time_timeline": current_time + seconds,
                            "duration_timeline": seconds_to_hhmmss(max(0, int(seconds))),
                            "zone_timeline": int(zone),  # Ensure zone is numeric
                            "description_timeline": interval["description"],
                            "tss_timeline": interval["tss"]
                        })
                        current_time += seconds
                
                x_ticks = format_x_ticks(current_time)
                label_expr = "{ " + ", ".join([f"{k}: '{v}'" for k, v in x_ticks.items()]) + " }[datum.value] || ''"
                log_debug(f"label_expr: {label_expr}")
                # Convert to DataFrame
                timeline_df = pd.DataFrame(timeline_data)
                log_debug(f"Timeline DataFrame:\n{timeline_df}")
                log_debug(f"Timeline DataFrame todict records: {timeline_df.to_dict(orient='records')}")
        

                chart_spec3 = {
                    "width": 800,
                    "height": 400,
                    "data": {"values": timeline_df.to_dict(orient="records")},
                    "mark": {"type": "rect"},
                    "encoding": {
                        "x": {
                            "field": "start_time_timeline",
                            "type": "quantitative",
                            "title": "Time",
                            "axis": {
                                "title": "Time",
                                "values": list(x_ticks.keys()),
                                "labelExpr": label_expr
                            }
                        },
                        "x2": {
                            "field": "end_time_timeline",
                            "type": "quantitative"
                        },
                        "y": {
                            "field": "zone_timeline",
                            "type": "quantitative",
                            "title": "Zone",
                            "scale": {"domain": [0, 7]},
                            "axis": {
                                "values": [0, 1, 2, 3, 4, 5, 6, 7],
                                "title": "Zone"
                            }
                        },
                        "color": {
                            "field": "zone_timeline",
                            "type": "quantitative",
                            "scale": {
                                "domain": [1, 7],
                                "range": ["#ADD8E6", "#FF0000"]  
                            },
                            "legend": {"title": "Zone"}
                        },
                        "tooltip": [
                            {"field": "description_timeline", "type": "nominal", "title": "Interval"},
                            {"field": "duration_timeline", "type": "nominal", "title": "Duration (s)"},
                            {"field": "zone_timeline", "type": "quantitative", "title": "Zone"},
                            {"field": "tss_timeline", "type": "quantitative", "title": "TSS"}
                        ]
                    }
                }
                # Render the chart
                st.vega_lite_chart(chart_spec3, use_container_width=True)

            else:
                st.error("No interval suggestions found for the selected workout.")
        else:
            st.error("No data found for the selected week.")
