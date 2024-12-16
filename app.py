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

# from streamlit_vega_lite import vega_lite_events
logging.basicConfig(filename="output.log", level=logging.INFO)

# Load local environment variables if running locally
if not st.secrets:
    load_dotenv()



cookies = EncryptedCookieManager(
    prefix="my_app",  # Replace with your app's name or namespace
    password="supersecret",  # Ensure this is secure
)

if cookies.ready():
    # Get or set the session ID in the cookie
    if "session_id" not in cookies:
        cookies["session_id"] = str(uuid.uuid4())
        cookies.save()

    # Retrieve the session ID from the cookie
    session_id = cookies["session_id"]
    st.write(f"Your session ID: {session_id}")
else:
    st.warning("Cookies are not ready or supported!")

# Use Streamlit secrets management
client_id = st.secrets.get("strava", {}).get("client_id", os.getenv("STRAVA_CLIENT_ID"))
client_secret = st.secrets.get("strava", {}).get("client_secret", os.getenv("STRAVA_CLIENT_SECRET"))
redirect_uri = st.secrets.get("strava", {}).get("redirect_uri", os.getenv("STRAVA_REDIRECT_URI"))
scopes = "read,activity:read_all"

connection_parameters = {
    "account": st.secrets.get("snowflake", {}).get("account", os.getenv("SNOWFLAKE_ACCOUNT")),
    "user": st.secrets.get("snowflake", {}).get("user", os.getenv("SNOWFLAKE_USER")),
    "password": st.secrets.get("snowflake", {}).get("password", os.getenv("SNOWFLAKE_PASSWORD")),
    "role": st.secrets.get("snowflake", {}).get("role", os.getenv("SNOWFLAKE_ROLE")),
    "warehouse": st.secrets.get("snowflake", {}).get("warehouse", os.getenv("SNOWFLAKE_WAREHOUSE")),
    "database": st.secrets.get("snowflake", {}).get("database", os.getenv("SNOWFLAKE_DATABASE")),
    "schema": st.secrets.get("snowflake", {}).get("schema", os.getenv("SNOWFLAKE_SCHEMA")),
}


def log_debug(message):
    logging.debug(message)


def log_info(message):
    # add timestamp to message
    message = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}"
    logging.info(message)


def log_error(message):
    logging.error(message)


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
    log_info("Planning week loads")
    log_info(loadsInfo)
    log_info(datesInfo)
    log_info(raceInfo)
    log_info(weekInfo)
    log_info(currentPlannedMacrocycles)
    log_info(currentPlannedMicrocycles)
    log_info(completedWorkouts)

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

    mondayBeginningOfPreComp = dateOfStartPreComp - timedelta(
        days=dateOfStartPreComp.weekday()
    )
    numberOfWeeksAvailableFondSpe = (
        dateOfStartPreComp
        - date(
            datesInfo["currentDate"].year,
            datesInfo["currentDate"].month,
            datesInfo["currentDate"].day,
        )
        - timedelta(days=7)
    ).days // 7 # begins after the current week
    if currentMicrocycle == {} and race_number == 0 and dateOfStartPreComp.weekday() != 0:
        numberOfWeeksAvailableFondSpe += 1
    log_info(
        f"Date of start precomp: {dateOfStartPreComp}, monday before precomp: {mondayBeginningOfPreComp}, number of weeks available fond spe: {numberOfWeeksAvailableFondSpe}"
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
        if week["theoreticalResting"]:
            continue
        if "Long" in week.get("keyWorkouts", None):
            week["theoreticalLongWorkoutTSS"] = currentHandableBiggestWorkout
            number_of_future_weeks_having_long_in_key_workouts = 0
            for future_week in planBeforePreComp[i + 1 :]:
                if "Long" in future_week.get("keyWorkouts", []):
                    number_of_future_weeks_having_long_in_key_workouts += 1

            currentHandableBiggestWorkout += (
                loadsInfo.get("finalLongRunTSS", loadsInfo["maxTssPerWorkout"])
                - currentHandableBiggestWorkout
            ) / (number_of_future_weeks_having_long_in_key_workouts + 1)

        if "ShortIntensity" in week.get("keyWorkouts", None):
            week["theoreticalShortIntensityTSS"] = currentHandableShortIntensity
            number_of_future_weeks_having_short_in_key_workouts = 0
            for future_week in planBeforePreComp[i + 1 :]:
                if "ShortIntensity" in future_week.get("keyWorkouts", []):
                    number_of_future_weeks_having_short_in_key_workouts += 1

            currentHandableShortIntensity += (
                loadsInfo.get("finalShortIntensityTSS", loadsInfo["maxTssPerWorkout"])
                - currentHandableShortIntensity
            ) / (number_of_future_weeks_having_short_in_key_workouts + 1)

        if "theoreticalRaceIntensityTSS" in week.get("keyWorkouts", None):
            week["theoreticalRaceIntensityTSS"] = currentHandableRaceIntensity
            number_of_future_week_having_race_in_key_workouts = 0
            for future_week in planBeforePreComp[i + 1 :]:
                if "RaceIntensity" in future_week.get("keyWorkouts", []):
                    number_of_future_week_having_race_in_key_workouts += 1
            currentHandableRaceIntensity += (
                loadsInfo.get("finalRaceIntensityTSS", loadsInfo["maxTssPerWorkout"])
                - currentHandableRaceIntensity
            ) / (number_of_future_week_having_race_in_key_workouts + 1)

        if "LongIntensity" in week.get("keyWorkouts", None):
            week["theoreticalLongIntensityTSS"] = currentHandableLongIntensity
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
                        "startDate": datesInfo["endDate"]
                        - timedelta(
                            days=MAX_CYCLES_TIMING_DAYS_TO_RACE_BY_OBJECTIVE_BY_OBJECTIVE_SIZE[
                                raceInfo["objective"]
                            ][raceInfo["eventSize"]]["Compet"]
                        ) + timedelta(days=1),
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
                "startDate": datesInfo["endDate"]
                - timedelta(
                    days=MAX_CYCLES_TIMING_DAYS_TO_RACE_BY_OBJECTIVE_BY_OBJECTIVE_SIZE[
                        raceInfo["objective"]
                    ][raceInfo["eventSize"]]["Compet"]
                ) + timedelta(days=1),
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
                        "startDate": datesInfo["endDate"]
                        - timedelta(
                            days=MAX_CYCLES_TIMING_DAYS_TO_RACE_BY_OBJECTIVE_BY_OBJECTIVE_SIZE[
                                raceInfo["objective"]
                            ][raceInfo["eventSize"]]["Compet"]
                        ) + timedelta(days=1),
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
                "startDate": datesInfo["endDate"]
                - timedelta(
                    days=MAX_CYCLES_TIMING_DAYS_TO_RACE_BY_OBJECTIVE_BY_OBJECTIVE_SIZE[
                        raceInfo["objective"]
                    ][raceInfo["eventSize"]]["Compet"]
                ) + timedelta(days=1),
                "endDate": datesInfo["endDate"],
                "theoreticalWeeklyTSS": raceInfo["eventTSS"]
                * COMPET_CYCLE_TSS_MULTIPLICATOR_BY_SPORT_BY_OBJECTIVE_OBJECTIVE_SIZE[
                    raceInfo["mainSport"]
                ][raceInfo["objective"]][raceInfo["eventSize"]],
            }
            currentPlanningDate = competitionMicrocycle["startDate"]
        log_debug("Current planning date")
        log_debug(currentPlanningDate)
        log_debug(datesInfo["currentDate"])
        if datesInfo["currentDate"] >= datetime(
            currentPlanningDate.year, currentPlanningDate.month, currentPlanningDate.day
        ):
            # We are in the competition cycle
            log_debug("We are in the competition cycle")
            planAnotherWeek = False
        else:
            log_debug("We are before the competition cycle")
            currentStep = "Pre-Compet"

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
                        "startDate": competitionMacrocycle["startDate"]
                        - timedelta(
                            days=MAX_CYCLES_TIMING_DAYS_TO_RACE_BY_OBJECTIVE_BY_OBJECTIVE_SIZE[
                                raceInfo["objective"]
                            ][raceInfo["eventSize"]]["Pre-Compet"]
                        ),
                        "totalTSS": loadsInfo["endLoad"]
                        / 2
                        * MAX_CYCLES_TIMING_DAYS_TO_RACE_BY_OBJECTIVE_BY_OBJECTIVE_SIZE[
                            raceInfo["objective"]
                        ][raceInfo["eventSize"]]["Pre-Compet"]
                        / 7,
                        "theoreticalResting": True,
                    },
                )
        if not found:
            log_debug("Creating precompet macrocycle")
            precompetMacrocycle = {
                "cycleType": "Pre-Compet",
                "startDate": competitionMacrocycle["startDate"]
                - timedelta(
                    days=MAX_CYCLES_TIMING_DAYS_TO_RACE_BY_OBJECTIVE_BY_OBJECTIVE_SIZE[
                        raceInfo["objective"]
                    ][raceInfo["eventSize"]]["Pre-Compet"]
                ),
                "endDate": competitionMacrocycle["startDate"] - timedelta(days=1),
                "theoreticalWeeklyTSS": loadsInfo["endLoad"]
                / 2
                * MAX_CYCLES_TIMING_DAYS_TO_RACE_BY_OBJECTIVE_BY_OBJECTIVE_SIZE[
                    raceInfo["objective"]
                ][raceInfo["eventSize"]]["Pre-Compet"]
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
                        "startDate": competitionMicrocycle["startDate"]
                        - timedelta(
                            days=MAX_CYCLES_TIMING_DAYS_TO_RACE_BY_OBJECTIVE_BY_OBJECTIVE_SIZE[
                                raceInfo["objective"]
                            ][raceInfo["eventSize"]]["Pre-Compet"]
                        ),
                        "theoreticalWeeklyTSS": loadsInfo["endLoad"]
                        / 2
                        * MAX_CYCLES_TIMING_DAYS_TO_RACE_BY_OBJECTIVE_BY_OBJECTIVE_SIZE[
                            raceInfo["objective"]
                        ][raceInfo["eventSize"]]["Pre-Compet"]
                        / 7,
                        "theoreticalResting": True,
                    },
                )
                currentPlanningDate = precompetMicrocycle["startDate"]
        if not found:
            log_debug("Creating precompet microcycle")
            precompetMicrocycle = {
                "cycleType": "Pre-Compet",
                "startDate": competitionMicrocycle["startDate"]
                - timedelta(
                    days=MAX_CYCLES_TIMING_DAYS_TO_RACE_BY_OBJECTIVE_BY_OBJECTIVE_SIZE[
                        raceInfo["objective"]
                    ][raceInfo["eventSize"]]["Pre-Compet"]
                ),
                "endDate": competitionMicrocycle["startDate"] - timedelta(days=1),
                "theoreticalWeeklyTSS": loadsInfo["endLoad"]
                / 2
                * MAX_CYCLES_TIMING_DAYS_TO_RACE_BY_OBJECTIVE_BY_OBJECTIVE_SIZE[
                    raceInfo["objective"]
                ][raceInfo["eventSize"]]["Pre-Compet"]
                / 7,
                "theoreticalResting": True,
            }
            currentPlanningDate = precompetMicrocycle["startDate"]
        log_info(f"Current planning date {currentPlanningDate}. Current date {datesInfo['currentDate']}")

        if datesInfo["currentDate"] >= datetime(
            currentPlanningDate.year, currentPlanningDate.month, currentPlanningDate.day
        ):
            # We are in the precompet cycle
            log_debug("We are in the precompet cycle")
            planAnotherWeek = False
        else:
            log_debug("We are before the precompet cycle")
            currentStep = "Before Pre Comp"
    if currentStep == "Before Pre Comp":
        # We begin next monday after current date
        newPlanBeforePreComp = []
        
        
        if currentMicrocycle == {} and race_number == 0:
            # Add a currentMicrocycle
            currentMicrocycleBeforePreComp = {
                "cycleType": "Fondamental",
                "startDate": datesInfo["currentDate"],
                "endDate": datesInfo["currentDate"]+timedelta(days=6-datesInfo["currentDate"].weekday()),
                "theoreticalWeeklyTSS": startLoad*((6-datesInfo["currentDate"].weekday())/7) if loadsInfo.get("nextRestingWeek", 4) >=1  else startLoad*((6-datesInfo["currentDate"].weekday())/7/2),
                "theoreticalResting": loadsInfo.get("nextRestingWeek", 4) >=1,
                "keyWorkouts": [],
                "dayByDay": {},
            }
            log_info(f"Creating current microcycle {currentMicrocycleBeforePreComp}")
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
                log_info(
                    f"Updating microcycle {newMicrocycle}, currentPlanningDate: {currentPlanningDate}"
                )
            else:
                newMicrocycle["startDate"] = currentPlanningDate
                newMicrocycle["endDate"] = currentPlanningDate + timedelta(days=6)
                log_info(
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
    log_info("Past microcycles")
    log_info(pastMicrocycles)
    log_info("Current microcycle")
    log_info(currentMicrocycle)
    log_info("New Plan Before Pre Comp")
    log_info(newPlanBeforePreComp)
    log_info("Precompet microcycle")
    log_info(precompetMicrocycle)
    log_info("Competition microcycle")
    log_info(competitionMicrocycle)
    for microcycle in newPlanBeforePreComp:
        microcycle = planFutureWeekDayByDay(microcycle, weekInfo, raceInfo, loadsInfo, datesInfo)
    precompetMicrocycle = planFutureWeekDayByDay(precompetMicrocycle, weekInfo, raceInfo, loadsInfo, datesInfo)
    competitionMicrocycle = planFutureWeekDayByDay(competitionMicrocycle, weekInfo, raceInfo, loadsInfo, datesInfo)
    totalMicrocycles = (
        pastMicrocycles + [currentMicrocycle]
        if currentMicrocycle != {}
        else [] + newPlanBeforePreComp + [precompetMicrocycle] + [competitionMicrocycle]
    )

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
    log_info(f"Theoretical time in zone {theoreticalTimeInZone}")

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
        log_info("Planning long workout")
        # let's split futureMicrocycle["theoreticalLongWorkoutTSS"] TSS in zones 1 2 and 3 with 30% 50% and 20% of the time respectively

        z1Percentage = 0.3
        z2Percentage = 0.5
        z3Percentage = 0.2

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

        dayByDay[weekInfo["longWorkoutDay"]] = [
            {
                "workoutType": "Long",
                "activity": raceInfo["mainSport"],
                "tss": activity_tss,
                "secondsInZone": {1: tz1, 2: tz2, 3: tz3},
                "theoreticalDistance": theoreticalDistance,
                "theoreticalTime": timedelta(seconds=tz1 + tz2 + tz3),
            }
        ]

        remaining_tss -= activity_tss

        theoreticalTimeInZone[1] -= tz1
        theoreticalTimeInZone[2] -= tz2
        theoreticalTimeInZone[3] -= tz3
        if weekInfo["longWorkoutDay"] in availableDays:
            availableDays.remove(weekInfo["longWorkoutDay"])
            dayAvailableDurations[weekInfo["longWorkoutDay"]] -= tz1 + tz2 + tz3
        log_info(dayByDay)

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
        log_info("Planning short intensity workout")
        # let's split futureMicrocycle["theoreticalShortIntensityTSS"] TSS in zones 5 6 and 7 with 50% 30% and 20% of the time respectively

        total_tss, secondsInZone = createWorkout(
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
        log_info(
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
                }
            )
            for zone in ZONES[raceInfo["mainSport"]].keys():
                theoreticalTimeInZone[zone] -= secondsInZone[zone]

            dayAvailableDurations[best_fit[0]] -= total_seconds
            # if dayAvailableDurations[best_fit[0]] <= 0:
            availableDays.remove(best_fit[0])

        log_info(dayByDay)
    if "LongIntensity" in futureMicrocycle.get("keyWorkouts", []):
        log_info("Planning long intensity workout")
        total_tss, secondsInZone = createWorkout(
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
        log_info(
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
                }
            )
            for zone in ZONES[raceInfo["mainSport"]].keys():
                theoreticalTimeInZone[zone] -= secondsInZone[zone]

            dayAvailableDurations[best_fit[0]] -= total_seconds
            # if dayAvailableDurations[best_fit[0]] <= 0:
            availableDays.remove(best_fit[0])
        log_info(dayByDay)

    if "RaceIntensity" in futureMicrocycle.get("keyWorkouts", []):
        log_info("Planning race intensity workout")
        total_tss, secondsInZone = createWorkout(
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
                }
            )
            for zone in ZONES[raceInfo["mainSport"]].keys():
                theoreticalTimeInZone[zone] -= secondsInZone[zone]

            dayAvailableDurations[best_fit[0]] -= total_seconds
            # if dayAvailableDurations[best_fit[0]] <= 0:
            availableDays.remove(best_fit[0])
        log_info(dayByDay)
    remaining_tss = futureMicrocycle["theoreticalWeeklyTSS"] - sum(
        [workout["tss"] for day in dayByDay.values() for workout in day]
    )
    # Let's plan the remaining time in zones
    while remaining_tss > 30:
        log_info("Planning a new workout")
        zones = []
        for zone in ZONES[raceInfo["mainSport"]].keys():
            if theoreticalTimeInZone[zone] > 0:
                zones.append(zone)
        zones = sorted(zones, key=lambda x: x, reverse=True)

        total_tss, secondsInZone = createWorkout(
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
        log_info(f"New workout, seconds in zone {secondsInZone}, total tss {total_tss}")

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
        log_info("Best fit")
        log_info(best_fit)
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
                }
            )
            for zone in ZONES[raceInfo["mainSport"]].keys():
                theoreticalTimeInZone[zone] -= secondsInZone[zone]

            dayAvailableDurations[best_fit[0]] -= total_seconds
            if best_fit[0] in availableDays:
                availableDays.remove(best_fit[0])
        remaining_tss -= total_tss

        log_info(dayByDay)

    futureMicrocycle["dayByDay"] = dayByDay

    return futureMicrocycle


def findBestFitDay(total_seconds, available_days, available_durations):
    log_info(
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
    log_info(f"Best fit day: {best_fit}")
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
    warmup_duration=600,
    cooldown_duration=600,
    activity="Run",
):
    log_info("Creating workout with params: ")
    log_info(
        f"min_tss: {min_tss}, max_tss: {max_tss}, target_tss: {target_tss}, remaining_time_in_zone: {remaining_time_in_zone}, min_time_in_zones: {min_time_in_zones}, max_time_in_zones: {max_time_in_zones}, cumulative_max_tss_in_zones: {cumulative_max_tss_in_zones}, zones: {zones}, warmup_duration: {warmup_duration}, cooldown_duration: {cooldown_duration}, activity: {activity}"
    )
    total_tss = 0
    secondsInZone = {zone: 0 for zone in ZONES[activity].keys()}
    remaining_tss = target_tss
    log_debug("TSS to reach")
    log_debug(remaining_tss)

    # Warmup
    secondsInZone[1] = warmup_duration
    warmup_tss = round(TSS_BY_ZONE_BY_SPORT[activity][1] * warmup_duration / 3600)
    total_tss += warmup_tss
    remaining_tss -= warmup_tss

    # Cooldown
    secondsInZone[1] = secondsInZone[1] + cooldown_duration
    cooldown_tss = round(TSS_BY_ZONE_BY_SPORT[activity][1] * cooldown_duration / 3600)
    total_tss += cooldown_tss
    remaining_tss -= cooldown_tss

    log_debug("Remaining TSS after warmup and cooldown")
    log_debug(remaining_tss)

    for zone in zones:
        log_info(f"Zone {zone}, remaining time in zone {remaining_time_in_zone[zone]}")
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

            log_info(
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
            log_info(
                f"seconds_in_zone {seconds_in_zone}, tss {tss}, recovery_tss {recovery_tss}"
            )

    # if we are under the min tss, we add half Z1 half Z2 time
    if remaining_tss > 0:
        log_info("Adding z1 and Z2 time")
        log_info("Remaining TSS for this activity: ")
        log_info(remaining_tss)
        log_info("Remaining time in zone")
        log_info(remaining_time_in_zone)
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

    return total_tss, secondsInZone


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


def compute_training_plan(inputs):
    result = []
    for i in range(len(inputs["races"])):
        log_info(f"Computing training plan for {i} race")
        log_info(f"Inputs: {inputs}")
        if inputs["races"][i]["distance"] >= 0:
            new_weeks = compute_training_plan_1_race(inputs, i)
            result = result + new_weeks
    return result


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
    nextRestingWeek = inputs["next_resting_week"]
    declaredHandableLoad = inputs["weekly_hours"] * (
        60
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

        startDate = lastRaceDate + timedelta(days=(7 - lastRaceDate.weekday() if lastRaceDate.weekday() >= 4 else 0))
        currentDate = lastRaceDate + timedelta(days=(7 - lastRaceDate.weekday() if lastRaceDate.weekday() >= 4 else 0))
    else:
        startDate = datetime.now()
        currentDate = datetime.now()
    
    
    currentDate = datetime(currentDate.year, currentDate.month, currentDate.day)
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
        "recuperation_level": "High",
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
        "intensity_workouts": st.session_state["input_intensity_workouts"],
        "longest_workout_hours": st.session_state["input_longest_workout_hours"],
        "longest_workout_minutes": st.session_state["input_longest_workout_minutes"],
        "next_resting_week": st.session_state["input_next_resting_week"],
        # "volume": st.session_state["input_volume"],
        "increase": st.session_state["input_increase"],
        # "intensity": st.session_state["input_intensity"]
    }
    result["races"] = update_race_data()
    result["week_organization"] = update_week_organization()
    st.session_state["inputs"].update(result)

    # Trigger recompute
    st.session_state["mock_data"] = compute_training_plan(st.session_state["inputs"])


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

def fetch_activities(after_ts):
    activities = []
    page = 1
    while True:
        url = f"https://www.strava.com/api/v3/athlete/activities?after={after_ts}&page={page}&per_page=30"
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            st.error("Failed to fetch activities.")
            break
        batch = response.json()
        if not batch:
            break
        activities.extend(batch)
        page += 1
    return activities



# Check if we have an access token in session_state
if "access_token" not in st.session_state:
    st.session_state["access_token"] = None

# Parse query parameters
params = st.query_params

session = Session.builder.configs(connection_parameters).create()

session.sql("""
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER,
    name VARCHAR,
    start_date VARCHAR,
    distance FLOAT,
    moving_time INTEGER,
    elapsed_time INTEGER,
    total_elevation_gain FLOAT,
    type VARCHAR,
    PRIMARY KEY (id)
)
""").collect()

session.sql("""
CREATE TABLE IF NOT EXISTS microcycles (
    strava_id INTEGER,
    start_date VARCHAR,
    end_date VARCHAR,
    cycle_type VARCHAR,
    theoretical_weekly_tss FLOAT,
    PRIMARY KEY (strava_id, start_date)
)
""").collect()

session.sql("""
CREATE TABLE IF NOT EXISTS microcycle_days (
    strava_id INTEGER,
    start_date VARCHAR,
    day VARCHAR,
    workout_idx INTEGER,
    zone VARCHAR,
    seconds INTEGER,
    PRIMARY KEY (strava_id, start_date, day, workout_idx, zone)
)
""").collect()

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

    if response.status_code == 200:
        token_data = response.json()
        st.session_state["access_token"] = token_data["access_token"]
        # Assume you have athlete_id from the token_data after login
        athlete_id = token_data["athlete"]["id"]
        st.session_state["athlete_id"] = athlete_id
    else:
        st.error("Failed to exchange code for token. Check your credentials and redirect URI.")
        st.stop()

# If we still don't have a token, show login link
if st.session_state["access_token"] is None:
    st.write("You are not logged in.")
    authorize_url = (
        f"https://www.strava.com/oauth/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope={scopes}"
    )

    
    st.markdown(f"[Click here to login with Strava]({authorize_url})")
else:
    # We have a token. We can call Strava's API.
    st.write("You are logged in! Your access token is stored in session_state.")

    # Fetch activities from Strava
    access_token = st.session_state["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    now = datetime.utcnow()
    two_months_ago = now - timedelta(days=60)
    after_timestamp = int(two_months_ago.timestamp())
    


    activities = fetch_activities(after_timestamp)

    if activities:
        # Build a single MERGE statement with multiple values
        values_clause = ", ".join(["(?, ?, ?, ?, ?, ?, ?, ?)"] * len(activities))
        
        params = []
        for activity in activities:
            params.extend([
                activity["id"],
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
            AS vals(id, name, start_date, distance, moving_time, elapsed_time, total_elevation_gain, type)
        ) vals
        ON a.id = vals.id
        WHEN NOT MATCHED THEN
            INSERT (id, name, start_date, distance, moving_time, elapsed_time, total_elevation_gain, type)
            VALUES (vals.id, vals.name, vals.start_date, vals.distance, vals.moving_time, vals.elapsed_time, vals.total_elevation_gain, vals.type)
        """

        session.sql(query, params).collect()

        st.success(f"Downloaded and stored {len(activities)} activities from the last two months.")

# First Row: My Level Fields
st.header("Training Level and Preferences")
with st.container():
    st.subheader("My Level")
    col1, col2, col3, col4, col5, col6, col7, col8 = st.columns(8)

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
    with col2:
        recuperation_level = st.selectbox(
            "Recuperation Needs",
            ["Low", "High"],
            ["Low", "High"].index(st.session_state["inputs"]["recuperation_level"]),
            key="input_recuperation_level",
            on_change=update_training_preferences,
        )
        cycle_length = 3 if recuperation_level == "Low" else 4

    with col3:
        weekly_hours = st.slider(
            "Current Weekly Hours*",
            1,
            20,
            st.session_state["inputs"]["weekly_hours"],
            key="input_weekly_hours",
            on_change=update_training_preferences,
        )
    with col4:
        intensity_workouts = st.selectbox(
            "Intensity Workouts*",
            list(range(0, 6)),
            st.session_state["inputs"]["intensity_workouts"],
            key="input_intensity_workouts",
            on_change=update_training_preferences,
        )

    with col5:
        longest_workout_hours = st.number_input(
            "Longest Workout (hours)*",
            value=st.session_state["inputs"]["longest_workout_hours"],
            step=1,
            key="input_longest_workout_hours",
            on_change=update_training_preferences,
        )
    with col6:
        longest_workout_minutes = st.number_input(
            "Longest Workout (minutes)*",
            value=st.session_state["inputs"]["longest_workout_minutes"],
            step=1,
            key="input_longest_workout_minutes",
            on_change=update_training_preferences,
        )

    with col7:
        next_resting_week = st.number_input(
            "Next Resting Week",
            value=st.session_state["inputs"]["next_resting_week"],
            step=1,
            key="input_next_resting_week",
            on_change=update_training_preferences,
        )
    # with col8:
    #     volume = st.selectbox("Volume", ["Low", "Medium", "High"], ["Low", "Medium", "High"].index(st.session_state["inputs"]["volume"]), key="input_volume",on_change=update_training_preferences)

    with col8:
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

st.header("Race Planning")

st.button("Add Race", on_click=add_race)
# Create dynamic columns based on the number of races
columns = st.columns(min(len(st.session_state["inputs"]["races"]), 3))  # Limit to 3 columns at a time

for i, race in enumerate(st.session_state["inputs"]["races"]):
    with columns[i]:
        st.subheader(f"Race {i + 1}") 
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

# Full Row: Training Load Visualization
st.header("Training Load and Week Organization")

# Mock data for visualization
# data_cycles = compute_training_plan(st.session_state["inputs"])
if "mock_data" in st.session_state:
    data_cycles = st.session_state["mock_data"]
else:
    data_cycles = compute_training_plan(st.session_state["inputs"])
df_cycles = pd.DataFrame(data_cycles)
if "timeInZoneRepartition" in df_cycles.columns:
    df_cycles["timeInZoneRepartition"] = df_cycles["timeInZoneRepartition"].apply(
        lambda d: {str(k): v for k, v in d.items()} if isinstance(d, dict) else d
    )
df_cycles["startDate"] = pd.to_datetime(df_cycles["startDate"])
df_cycles["endDate"] = pd.to_datetime(df_cycles["endDate"])

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
log_debug("Data cycles")
log_debug(data_cycles)

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
                            "Seconds": seconds,
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
log_info(f"Final activity_df: {activity_df.to_string()}")

if "athlete_id" in st.session_state:
    start_dates = [cycle["startDate"] for cycle in data_cycles]
    athlete_id = st.session_state["athlete_id"]

    if start_dates:
        # Bulk delete existing microcycle_days and microcycles
        placeholders = ", ".join(["?"] * len(start_dates))
        
        # Delete from microcycle_days
        session.sql(
            f"DELETE FROM microcycle_days WHERE strava_id = ? AND start_date IN ({placeholders})",
            [athlete_id] + start_dates
        ).collect()
        
        # Delete from microcycles
        session.sql(
            f"DELETE FROM microcycles WHERE strava_id = ? AND start_date IN ({placeholders})",
            [athlete_id] + start_dates
        ).collect()

    # Bulk insert microcycles
    microcycle_values = []
    microcycle_params = []
    for cycle in data_cycles:
        microcycle_values.append("(?, ?, ?, ?, ?)")
        microcycle_params.extend([athlete_id, cycle["startDate"], cycle["endDate"], cycle["cycleType"], cycle["theoreticalWeeklyTSS"]])

    if microcycle_values:
        mc_val_str = ", ".join(microcycle_values)
        session.sql(f"""
        INSERT INTO microcycles (strava_id, start_date, end_date, cycle_type, theoretical_weekly_tss)
        VALUES {mc_val_str}
        """, microcycle_params).collect()

    # Bulk insert microcycle_days
    day_values = []
    day_params = []
    for cycle in data_cycles:
        if "dayByDay" in cycle:
            for day, day_activities in cycle["dayByDay"].items():
                for idx, activity in enumerate(day_activities):
                    for zone, seconds in activity["secondsInZone"].items():
                        day_values.append("(?, ?, ?, ?, ?, ?)")
                        day_params.extend([athlete_id, cycle["startDate"], day, idx + 1, zone, seconds])

    if day_values:
        day_val_str = ", ".join(day_values)
        session.sql(f"""
        INSERT INTO microcycle_days (strava_id, start_date, day, workout_idx, zone, seconds)
        VALUES {day_val_str}
        """, day_params).collect()

    st.success("Microcycles have been successfully stored or updated in the database!")



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

    # Extract the selected week from event
    if event and "selection" in event and "selector" in event["selection"]:
        selected_points = event["selection"]["selector"]
        if selected_points:
            # Extract endDate and convert from timestamp to datetime
            selected_week_timestamp = selected_points[0].get("endDate")
            if selected_week_timestamp is not None:
                selected_week_datetime = pd.to_datetime(selected_week_timestamp, unit="ms")
                st.session_state["selected_week"] = selected_week_datetime
            else:
                st.session_state.pop("selected_week", None)
        else:
            st.session_state.pop("selected_week", None)
    else:
        st.session_state.pop("selected_week", None)

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
        log_debug(f"Selected week: {selected_week}")

        # Filter data for the selected week (+1 day offset if required)
        filtered_activity_df = activity_df[
            activity_df["endDate"] == selected_week.date() + timedelta(days=1)
        ]

        # Merge to ensure all days are present
        filtered_activity_df = full_week_data.merge(
            filtered_activity_df, on="Day", how="left"
        ).fillna({"WorkoutIdx": 0, "Zone": "0", "Seconds": 0})

        # Set Day as categorical to control order
        filtered_activity_df["Day"] = pd.Categorical(
            filtered_activity_df["Day"], categories=WEEK_DAYS, ordered=True
        )

        if not filtered_activity_df.empty:
            # Check if multiple workouts per day exist
            max_workout_idx = filtered_activity_df["WorkoutIdx"].max()

            # Base chart
            chart = (
                alt.Chart(filtered_activity_df)
                .mark_bar()
                .encode(
                    x=alt.X("Day:O", title="Day", sort=WEEK_DAYS),
                    y=alt.Y("Seconds:Q", title="Time (seconds)", stack="zero"),
                    color=alt.Color(
                        "Zone:N",
                        scale=alt.Scale(scheme="category20b"),
                        legend=alt.Legend(title="Zones"),
                    ),
                    tooltip=["Zone", "Seconds", "WorkoutIdx"],
                )
                .properties(width=800, height=400)
                .configure_scale(
                    bandPaddingInner=0.3,  # Adjust inner padding
                    bandPaddingOuter=0.1,  # Adjust outer padding
                )
            )

            # Only add xOffset if more than one workout per day
            if max_workout_idx > 1:
                chart = chart.encode(xOffset="WorkoutIdx:N")

            st.altair_chart(chart, use_container_width=True)
        else:
            st.write("DEBUG: No activity data found for the selected week.")
    else:
        st.write("DEBUG: No week selected. Waiting for user interaction.")
