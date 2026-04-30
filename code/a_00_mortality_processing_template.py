"""
GENERALIZED PRISON MORTALITY DATA PROCESSING PIPELINE
==============================================================================================

This script processes incoming individual-level prison mortality datasets and links them to the
(now deprecated by the Trump administration) HIFLD prison facility boundaries dataset (when possible)
to enable spatial analysis related to death in custody. It is designed to be generalized for different
data sources while maintaining consistent output schema. Output dataset has lat longs for joining
to exposure data (e.g. temperature, air pollution, wildfire etc)

The script was designed to process state prison mortality data from
    a) state Departments of Corrections (DOCs) that publish individual-level records
    b) the Bureau of Justice Statistics Mortality in Correctional Institutions (MCI) dataset,
        https://www.ojp.gov/program/ojp-freedom-information-act/ojp-reading-room
    c) nongovernmental organizations including IncarcerationTransparency.org and
        https://texasjusticeinitiative.org and,
    d) the UCLA Law COVID-19 Behind Bars project

INPUTS: Modify the config and standardization dictionaries below for your dataset.
OUTPUTS: 1) A standardized, HIFLD-linked geocoded dataset with consistent column names and formats (output_path_linked). We also include
            records that do not have a clear HIFLD match but have spatial info such as an address or city (enabling extrapolation for exposure analyses).
            Users can choose to exclude those imprecise records from spatial analyses if desired, but we provide them in the output with
            a flag for transparency and potential future geocoding efforts.
         2) A dataset of records that could *not* be matched to HIFLD (output_path_unlinked) and have no other spatial information
==============================================================================================
"""

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import numpy as np
from difflib import get_close_matches
import 01_all_facility_dictionaries

try:
    from geopy.geocoders import ArcGIS, Nominatim
    from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
except Exception:
    ArcGIS = None
    Nominatim = None
    GeocoderTimedOut = Exception
    GeocoderUnavailable = Exception

# Suppress future deprecation warnings about downcasting in fillna operations
pd.set_option('future.no_silent_downcasting', True)

###--------------------------- USER CONFIGURATION ---------------------------###
### REQUIRED:
### 1. Modify the config section to match your input data file paths and columns
###     1a. A death date, a facility identifier (e.g. name or address), and a state column is required for this script
###     1b. You may also need to modify the mapping dictionaries below for attributes like state names, sex, race, or cause of death
### 2. If you have state-specific facility name/address dictionaries or state-specific cause of death dictionaries,
###     add them to all_facility_dictionaries.py and they will be automatically loaded by this script
###

config = {
    # (REQUIRED) FILE PATHS
    "mortality_path": './data/a_00_mortality_data_raw/combined_mortality_data_04012026.csv', # path to your mortality dataset that needs to be processed
    "hifld_path": "./data/z_other_datasets/prison_boundaries.csv",
    "output_path_linked": "./data/a_01_mortality_data_processed/state_docs_excl_2016_to_2019_04082026.csv",
    "output_path_unlinked": "./data/a_01_mortality_data_processed/no_geocode_mortality_data/unlinked_state_docs_excl_2016_to_2019_04082026.csv",

    # REQUIRED COLUMNS: death date and facility identifier from your mortality/health data
    "death_date_col": "DEATH_DATE",          # Column containing death date, e.g. '03/15/2020' (any format, date will be auto-parsed),
        # can provide date component columns if date is split across multiple columns (see death_year_col, death_month_col, death_day_col below)
    "facility_cols": ["FACILITY_NAME", "FACILITY_ABBREV"],    # List of facility identifier columns, e.g. facility_name or facility_abbrev; will try in order (first non-null value used)
    "address_col": "FACILITY_ADDRESS",             # Facility address (for fuzzy matching fallback)

    # REQUIRED: state/state abbreviation column - state code dictionaries provided in the next section, please review for your case
    "state_col": "STATE_ABBREV",            # Column with state (full name, mci code, or abbrev—will be auto-converted)

    # OPTIONAL date-component columns (if date is split across columns, only necessary if death_date_col is missing or unparseable)
    "death_year_col": "DEATH_YEAR",        # optional, e.g. '2020' used if death_date_col is missing or unparseable
    "death_month_col": "DEATH_MONTH",   # optional, e.g. '03' or 'March'
    "death_day_col": "DEATH_DAY",     # optional, e.g. '15'

    # OPTIONAL: date of birth information. Need *either* dob_col or dob_year/month/day
    "dob_col": "DATE_OF_BIRTH",                # Optional date of birth column, e.g. '12/01/1980' (date format will be auto-parsed)
    "dob_year_col": "BIRTH_YEAR",      # optional split DOB, e.g. '1980'
    "dob_month_col": None,      # optional split DOB, e.g. '12' or 'December'
    "dob_day_col": None,        # optional split DOB, e.g. '01'

    # OPTIONAL COLUMNS: if present, will be standardized
    "sex_col": ["SEX", "GENDER"], # Sex/gender column(s); can be a string or prioritized list (first non-empty value per row is used)
        # ^ Note: this was done because some states report 'sex' using the word 'gender'
    "race_col": "RACE",              # Race column - please review race_mapping dictionary to ensure your values will be standardized correctly
    "age_col": "AGE",                 # Age (if exists, will be coerced numeric, else will be calculated from DOB info if provided)
    "cause_col": "CAUSE_GENERAL",               # Cause of death as text/string
    "cause_key_col": "CAUSE_GENERAL_KEY",            # Cause key/code column, e.g. '1' corresponding to Illness; may be decoded using either cause_dict_name or {STATE}_cause_dict
    "cause_dict_name": None,            # Dataset-wide cause dictionary name. If omitted, falls back to {STATE}_cause_dict (located in all_facility_dictionaries.py if present).
    "city_col": "CITY",                    # City of facility (for address fallback)

    # OPTIONAL: CMP_ID join (if CMP_ID column exists, link via CMP_fac_data_UO.csv)
    #   CMP_ID is a unique identifier for prison facilities used in the UCLA Law custodial mortality project, https://github.com/uclalawcovid19behindbars/custodial_mortality_project/tree/main/Crosswalks
    "cmp_id_col": "CMP_ID",             # Optional column with CMP facility ID
    "cmp_data_path": "data/cmp_fac_data.csv",          # Path to CMP-to-HIFLD mapping file

    # OPTIONAL: additional metadata columns to preserve as a list of strings
    #"preserve_cols": ["Illspec", "Drugspec", "Selfspec", "Accspec", "Suicspec", "Homispec", "Otherspec", "Place"]
    "preserve_cols": ["CAUSE_SPECIFIC", "DAYS_INCARCERATED", "DATE_INCARCERATED", "MEDICAL_CAUSE", "Location", "INCIDENT_LOCATION"],  # List any important columns
}

def get_old_col(col):
    """Get the renamed column name with 'old_' prefix."""
    if col is None or not isinstance(col, str):
        return col
    return 'old_' + col.lower()


def get_config_old_cols(config, key, existing_cols=None):
    """Return configured column(s) with old_ prefix, optionally filtered to existing columns."""
    cols = config.get(key, [])
    if cols is None:
        return []
    if not isinstance(cols, list):
        cols = [cols]

    old_cols = [get_old_col(col) for col in cols if col]
    if existing_cols is not None:
        existing_set = set(existing_cols)
        old_cols = [col for col in old_cols if col in existing_set]
    return old_cols

###--------------------------- STANDARDIZATION DICTIONARIES ---------------------###

# Sex/Gender standardization
# Maps any input value (case-insensitive) to numeric code
sex_mapping = {
    'm': 1, 'male': 1, 'M': 1, 'Male': 1,
    'f': 2, 'female': 2, 'F': 2, 'Female': 2,
    'other': 0, 'Other': 0,
    'unknown': -1, 'Unknown': -1, '': -1, None: -1
}

# Race standardization (example from your existing code)
race_mapping = {
    1: 'White, non-Hispanic',
    2: 'Black, non-Hispanic',
    3: 'Hispanic or Latino',
    4: 'Native American',
    5: 'Asian, non-Hispanic',
    6: 'Pacific Islander',
    7: 'Other',
    8: 'Other',
    9: 'Other',
    'W': 'White, non-Hispanic',
    'B': 'Black, non-Hispanic',
    'H': 'Hispanic or Latino',
    'White': 'White, non-Hispanic',
    'WHITE': 'White, non-Hispanic',
    'White, unknown': 'White, non-Hispanic',
    'White, not of Hispanic origin': 'White, non-Hispanic',
    'White, non‐Hispanic': 'White, non-Hispanic',
    'White, non-Hispanic': 'White, non-Hispanic',
    'Caucasian': 'White, non-Hispanic',
    'CAUCASIAN': 'White, non-Hispanic',
    'CAU': 'White, non-Hispanic',
    'Black': 'Black, non-Hispanic',
    'BLACK': 'Black, non-Hispanic',
    'Black, non‐Hispanic': 'Black, non-Hispanic',
    'Black, non-hispanic': 'Black, non-Hispanic',
    'Black, Unknown': 'Black, non-Hispanic',
    'BLACK/AFRICAN AMERICAN': 'Black, non-Hispanic',
    'Black/African American': 'Black, non-Hispanic',
    'African American': 'Black, non-Hispanic',
    'AFRICAN AMERICAN': 'Black, non-Hispanic',
    'AFRICAN-AMERICAN': 'Black, non-Hispanic',
    'Black or African American': 'Black, non-Hispanic',
    'Black or African American, not of Hispanic origin': 'Black, non-Hispanic',
    'AA': 'Black, non-Hispanic', #assuming this is abbrev for African American
    'Hispanic': 'Hispanic or Latino',
    'HISPANIC': 'Hispanic or Latino',
    'White, hispanic': 'Hispanic or Latino',
    'Latino': 'Hispanic or Latino',
    'Hispanic/Latino': 'Hispanic or Latino',
    'HISPANIC/LATINO': 'Hispanic or Latino',
    'Hispanic or Latino': 'Hispanic or Latino',
    'LATINO': 'Hispanic or Latino',
    'CUBAN': 'Hispanic or Latino',
    'HIS': 'Hispanic or Latino', #making assumption
    'HS': 'Hispanic or Latino', #making assumption, small n
    'Asian': 'Asian, non-Hispanic',
    'ASIAN': 'Asian, non-Hispanic',
    'ASI': 'Asian, non-Hispanic', #making assumption, small n
    'ASIAN/ORTL': 'Asian, non-Hispanic',
    'Vietnamese': 'Asian, non-Hispanic',
    'Filipino': 'Asian, non-Hispanic',
    'Korean': 'Asian, non-Hispanic',
    'Chinese': 'Asian, non-Hispanic',
    'Japanese': 'Asian, non-Hispanic',
    'Cambodian': 'Asian, non-Hispanic',
    'Other Asian': 'Asian, non-Hispanic',
    'Asian Indian': 'Asian, non-Hispanic',
    'Laotian': 'Asian, non-Hispanic',
    'A': 'Asian, non-Hispanic', #making assumption, small n
    'AS': 'Asian, non-Hispanic', #making assumption, small n
    'AI': 'Native American', #making assumption that AI is American Indian, small n
    'Native American': 'Native American',
    'Native America': 'Native American',
    'NATIVE AMERICAN': 'Native American',
    'American Indian': 'Native American',
    'America n Indian': 'Native American',
    'AMERICAN INDIAN': 'Native American',
    'American Indian or Alaska Native': 'Native American',
    'American Indian or Alaskan Native': 'Native American',
    'AMERICAN INDIAN/ALASKAN NATIVE': 'Native American',
    'American Indian/Alaska Native': 'Native American',
    'Alaska Native': 'Native American',
    'NATIVE  AMERICAN': 'Native American',
    'Native Hawaiian': 'Pacific Islander',
    'Native Hawaiian or Pacific': 'Pacific Islander',
    'Pacific Islander': 'Pacific Islander',
    'PACIFIC ISLANDER': 'Pacific Islander',
    'Samoan': 'Pacific Islander',
    'Hawaiian': 'Pacific Islander',
    '2 or more races':'Other',
    'Other': 'Other',
    'OTHER': 'Other',
    'ASIAN/PACIFIC ISLANDER': 'Other',
    'Additional Racial category in your system': 'Other',
    'Unknown': 'Unknown',
    'UNKNOWN': 'Unknown',
    'MISSING/NONE': 'Unknown',
    'nan': 'Unknown',
    'Guamanian': 'Other'
    # Add other race string mappings as needed
}

# Based on MCI codebook, https://www.ojp.gov/program/ojp-freedom-information-act/ojp-reading-room
mci_cause_dict = {
    1: "Illness (exclude AIDS-related deaths), specify illness",
    2: "Acquired Immune Deficiency Syndrome (AIDS-related)",
    3: "Accidental Alcohol/drug intoxication (specify type)",
    4: "Accidental injury to self, describe events",
    5: "Accidental injury by other (e.g. vehicular accident during transport) – describe events",
    6: "Suicide (e.g. hanging, knife/cutting instrument, intentional drug overdose) – describe events",
    7: "Homicide (all years except 2011 and 2012)",
    8: "Other causes, specify causes",
    11: "Homicide (2011 and 2012 only)"
}

###-------- SECTION 0: Helper Functions & State/Dictionary Lookups --------###

# State name/code/abbrev lookup dictionaries
us_state_to_abbrev = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY", "District of Columbia": "DC",
    "American Samoa": "AS", "Guam": "GU", "Northern Mariana Islands": "MP",
    "Puerto Rico": "PR", "Virgin Islands, U.S.": "VI",
}

# NOTE: these are based on MCI codebook, https://www.ojp.gov/program/ojp-freedom-information-act/ojp-reading-room,
# these do not necessarily match the administrative FIPS mappings
state_code_to_abbrev = {
    1: "AL", 2: "AK", 3: "AZ", 4: "AR", 5: "CA", 6: "CO", 7: "CT", 8: "DE",
    10: "FL", 11: "GA", 12: "HI", 13: "ID", 14: "IL", 15: "IN", 16: "IA",
    17: "KS", 18: "KY", 19: "LA", 20: "ME", 21: "MD", 22: "MA", 23: "MI",
    24: "MN", 25: "MS", 26: "MO", 27: "MT", 28: "NE", 29: "NV", 30: "NH",
    31: "NJ", 32: "NM", 33: "NY", 34: "NC", 35: "ND", 36: "OH", 37: "OK",
    38: "OR", 39: "PA", 40: "RI", 41: "SC", 42: "SD", 43: "TN", 44: "TX",
    45: "UT", 46: "VT", 47: "VA", 48: "WA", 49: "WV", 50: "WI", 51: "WY",
}

st_abbrevs = ["AK", "AL", "AR", "AZ", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "IA",
              "ID", "IL", "IN", "KS", "KY", "LA", "MA", "MD", "ME", "MI", "MN", "MO",
              "MS", "MT", "NC", "ND", "NE", "NH", "NJ", "NM", "NV", "NY", "OH", "OK",
              "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VA", "VT", "WA", "WI",
              "WV", "WY", "DC", "AS", "GU", "MP", "PR", "VI"]

def get_state_dict(state, suffix='_facilities'):
    """Load state-specific facility dictionary from all_facility_dictionaries module."""
    key = f"{state}{suffix}"
    d = getattr(all_facility_dictionaries, key, {})
    return d if isinstance(d, dict) else {}


def get_named_dict(dict_name):
    """Load a dictionary by name from this module or all_facility_dictionaries."""
    if not dict_name or not isinstance(dict_name, str):
        return {}

    local_dict = globals().get(dict_name, {})
    if isinstance(local_dict, dict):
        return local_dict

    external_dict = getattr(all_facility_dictionaries, dict_name, {})
    return external_dict if isinstance(external_dict, dict) else {}


def get_cause_dict(config, state=None):
    """Return either a dataset-wide cause dict or a state-specific cause dict."""
    global_cause_dict_name = config.get('cause_dict_name')
    if global_cause_dict_name:
        return get_named_dict(global_cause_dict_name)

    if state:
        return get_state_dict(state, '_cause_dict')

    return {}

def normalize_state_abbrev(state_value):
    """
    Convert any state representation (full name, numeric code, or abbrev) to 2-letter abbrev.
    Returns None if unrecognized.
    """
    if pd.isna(state_value):
        return None

    state_str = str(state_value).strip()

    # Already an abbreviation?
    if state_str.upper() in st_abbrevs:
        return state_str.upper()

    # Try as full state name (case-insensitive)
    for name, abbrev in us_state_to_abbrev.items():
        if name.lower() == state_str.lower():
            return abbrev

    # Try as numeric state code
    try:
        code = int(state_str)
        if code in state_code_to_abbrev:
            return state_code_to_abbrev[code]
    except (ValueError, TypeError):
        pass

    # Unrecognized
    return None

def standardize_sex(sex_value):
    """Convert sex/gender value to numeric code (1=M, 2=F, 0=Other, -1=Unknown).
    If already numeric and valid, returns as-is."""
    if pd.isna(sex_value):
        return -1

    # If already numeric and valid, return as-is
    try:
        numeric_val = int(sex_value) if not isinstance(sex_value, (int, float)) else sex_value
        if numeric_val in [1, 2, 0, -1]:
            return numeric_val
    except (ValueError, TypeError):
        pass

    # Try string mapping
    sex_str = str(sex_value).strip().lower()
    return sex_mapping.get(sex_str, -1)

def standardize_race(race_value):
    """Convert race value using provided mapping dictionary."""
    if pd.isna(race_value):
        return None

    # Try direct lookup (handles both numeric and string keys)
    if race_value in race_mapping:
        return race_mapping[race_value]

    # Try case-insensitive string lookup
    if isinstance(race_value, str):
        race_str = race_value.strip().lower()
        for key, val in race_mapping.items():
            if isinstance(key, str) and key.lower() == race_str:
                return val

    return None

def parse_death_date_auto(date_value, reference_date=None, min_age=10, max_age=110, date_role='birth', max_future_years=1):
    """
        Attempt to parse date from multiple formats with robust 2-digit year handling.

        date_role behavior:
        - 'birth': use age-based century adjustment against reference_date (DOB-style parsing).
        - 'event': keep modern 2-digit years as-is (e.g., 20 -> 2020), but prevent implausible future years
            by shifting one century back when needed (e.g., 68 -> 1968 rather than 2068).

    - Returns pd.Timestamp or NaT if unsuccessful.

    Parameters:
    -----------
    date_value : str or datetime-like
        Date to parse
    reference_date : pd.Timestamp, optional
        Date to calculate age from / compare against (default: today)
    min_age : int
        Minimum reasonable age for DOB parsing (default: 10)
    max_age : int
        Maximum reasonable age for DOB parsing (default: 110)
    date_role : str
        'birth' or 'event'
    max_future_years : int
        For event parsing, allow dates up to this many years in the future before shifting century.
    """
    if pd.isna(date_value):
        return pd.NaT

    reference_date = reference_date or pd.Timestamp.now()
    date_str = str(date_value).strip()
    max_future_date = reference_date + pd.DateOffset(years=max_future_years)

    def normalize_event_candidate(candidate):
        """Adjust event dates that parse into implausible future centuries."""
        if pd.isna(candidate):
            return pd.NaT
        adjusted = candidate
        # Example: 01/01/68 may parse as 2068; shift back to 1968 for event dates.
        while adjusted > max_future_date:
            adjusted = adjusted.replace(year=adjusted.year - 100)
        return adjusted

    # Try common formats (including 2-digit year variants)
    formats_2digit = ['%m/%d/%y', '%d/%m/%y']
    formats_4digit = ['%m/%d/%Y', '%Y-%m-%d', '%d/%m/%Y', '%Y%m%d']

    # First try 4-digit year formats (unambiguous)
    for fmt in formats_4digit:
        try:
            candidate = pd.to_datetime(date_str, format=fmt, errors='coerce')
            if pd.notna(candidate):
                if date_role == 'event':
                    return normalize_event_candidate(candidate)

                # DOB parsing path: validate age is reasonable
                age = (reference_date - candidate).days // 365
                if min_age <= age <= max_age:
                    return candidate
        except:
            pass

    # Then try 2-digit year formats with century adjustment
    for fmt in formats_2digit:
        try:
            # Parse with default century (pandas uses 2000s for 00-68, 1900s for 69-99)
            candidate = pd.to_datetime(date_str, format=fmt, errors='coerce')
            if pd.notna(candidate):
                if date_role == 'event':
                    return normalize_event_candidate(candidate)

                age = (reference_date - candidate).days // 365

                # If age is unreasonable, try the alternate century
                if age < min_age or age > max_age:
                    # Flip century: if 2000s, try 1900s and vice versa
                    if candidate.year >= 2000:
                        # Try 1900s: subtract 100 years
                        candidate_alt = candidate.replace(year=candidate.year - 100)
                    else:
                        # Try 2000s: add 100 years
                        candidate_alt = candidate.replace(year=candidate.year + 100)

                    age_alt = (reference_date - candidate_alt).days // 365
                    if min_age <= age_alt <= max_age:
                        return candidate_alt
                else:
                    return candidate
        except:
            pass

    # Try pandas auto-parsing as last resort
    try:
        candidate = pd.to_datetime(date_str, errors='coerce')
        if pd.notna(candidate):
            if date_role == 'event':
                return normalize_event_candidate(candidate)

            age = (reference_date - candidate).days // 365
            # Even with auto-parse, validate age is in reasonable range
            if min_age <= age <= max_age:
                return candidate
            # If auto-parse gave unreasonable age and it's a 2-digit year issue, try alternate
            elif candidate.year >= 2000 and age < min_age:
                candidate_alt = candidate.replace(year=candidate.year - 100)
                age_alt = (reference_date - candidate_alt).days // 365
                if min_age <= age_alt <= max_age:
                    return candidate_alt
    except:
        pass

    return pd.NaT


def parse_date_from_components(df, year_col, month_col, day_col):
    """Build datetime Series from component columns if they exist, or NaT otherwise."""
    if not all(col in df.columns for col in [year_col, month_col, day_col]):
        return pd.Series(pd.NaT, index=df.index)

    # Month name to number mapping
    month_name_to_num = {
        'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
        'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
        'January': 1, 'February': 2, 'March': 3, 'April': 4, 'May': 5, 'June': 6,
        'July': 7, 'August': 8, 'September': 9, 'October': 10, 'November': 11, 'December': 12,
        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
        'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
        'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
        'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12,
    }

    # Convert components to numeric, handling month names
    year_series = pd.to_numeric(df[year_col], errors='coerce').fillna(0).astype(int)
    month_series = df[month_col].map(month_name_to_num).fillna(df[month_col]).infer_objects(copy=False)
    month_series = pd.to_numeric(month_series, errors='coerce').fillna(0).astype(int)
    day_series = pd.to_numeric(df[day_col], errors='coerce').fillna(0).astype(int)

    # Create date strings from components, handling NA values
    date_str = (
        year_series.astype(str).str.zfill(4) + '-' +
        month_series.astype(str).str.zfill(2) + '-' +
        day_series.astype(str).str.zfill(2)
    )

    # Set to NaT if any component is NA
    date_str = date_str.where(
        (df[year_col].notna()) & (df[month_col].notna()) & (df[day_col].notna()),
        pd.NaT
    )

    return pd.to_datetime(date_str, errors='coerce')


def backfill_hifld_cols(df, mask, name_to_id, name_to_addr, name_to_city):
    """Backfill HIFLD columns (facilityid, hifld_address, hifld_city) based on matched hifld_name."""
    df.loc[mask, 'facilityid'] = df.loc[mask, 'hifld_name'].map(name_to_id)
    df.loc[mask, 'hifld_address'] = df.loc[mask, 'hifld_name'].map(name_to_addr)
    df.loc[mask, 'hifld_city'] = df.loc[mask, 'hifld_name'].map(name_to_city)


def should_fuzzy_match_facility_token(value):
    """Skip fuzzy matching for short code-like tokens (e.g., DWH, DWH/JCF)."""
    if pd.isna(value):
        return False

    token = str(value).strip()
    if not token or token.lower() == 'nan':
        return False

    # Very short, no-space facility codes are too ambiguous for fuzzy matching.
    if len(token) <= 4 and ' ' not in token:
        return False

    # Composite code-like forms (e.g., DWH/JCF, DCI-I) are also too ambiguous.
    if ' ' not in token and ('/' in token or '-' in token):
        parts = [p for p in re.split(r'[/-]+', token) if p]
        if parts and all(len(p) <= 4 for p in parts):
            return False

    return True


def _has_text(series):
    """Return boolean mask for non-empty, non-'nan' text values."""
    s = series.astype(str).str.strip()
    return series.notna() & s.ne('') & s.str.lower().ne('nan')


def geocode_records(df, config, city_col_old):
    """
    Build geocoding query strings using explicit priority rules and populate latitude/longitude.
    Priority:
      1) hifld_address + hifld_city + state_abbrev
      2) match_method == address_dict_no_hifld: facility_address
      3) match_method == facility_address: facility_address + city + state_abbrev
      4) match_method == none: city + state_abbrev
    """
    if ArcGIS is None or Nominatim is None:
        print("  (geopy not available; skipping geocoding)")
        df['latitude'] = pd.NA
        df['longitude'] = pd.NA
        return df

    if 'match_method' not in df.columns:
        print("  (No match_method column; skipping geocoding)")
        df['latitude'] = pd.NA
        df['longitude'] = pd.NA
        return df

    # Configurable geocoding settings (with safe defaults).
    cache_path = config.get('geocode_cache_path', 'analysis_datasets/d/geocode_cache.csv')
    geocoder_timeout = int(config.get('geocode_timeout', 10))
    max_retries = int(config.get('geocode_max_retries', 3))
    base_delay = float(config.get('geocode_base_delay', 1.0))
    arcgis_workers = int(config.get('geocode_arcgis_workers', 5))
    nominatim_min_delay = float(config.get('nominatim_min_delay', 1.0))
    nominatim_user_agent = config.get(
        'nominatim_user_agent',
        'mortality_processing_template/1.0 (contact: local_user)'
    )

    # Ensure lat/lon columns exist before fill.
    if 'latitude' not in df.columns:
        df['latitude'] = pd.NA
    if 'longitude' not in df.columns:
        df['longitude'] = pd.NA

    query = pd.Series(pd.NA, index=df.index, dtype='object')

    has_hifld_addr = _has_text(df['hifld_address']) if 'hifld_address' in df.columns else pd.Series(False, index=df.index)
    has_hifld_city = _has_text(df['hifld_city']) if 'hifld_city' in df.columns else pd.Series(False, index=df.index)
    has_state = _has_text(df['state_abbrev']) if 'state_abbrev' in df.columns else pd.Series(False, index=df.index)
    has_fac_addr = _has_text(df['facility_address']) if 'facility_address' in df.columns else pd.Series(False, index=df.index)
    has_city = _has_text(df[city_col_old]) if city_col_old and city_col_old in df.columns else pd.Series(False, index=df.index)

    # 1) Primary: full HIFLD address components
    mask1 = has_hifld_addr & has_hifld_city & has_state
    query.loc[mask1] = (
        df.loc[mask1, 'hifld_address'].astype(str).str.strip() + ', ' +
        df.loc[mask1, 'hifld_city'].astype(str).str.strip() + ', ' +
        df.loc[mask1, 'state_abbrev'].astype(str).str.strip()
    )

    # 2) address_dict_no_hifld: facility_address only
    mask2 = query.isna() & (df['match_method'] == 'address_dict_no_hifld') & has_fac_addr
    query.loc[mask2] = df.loc[mask2, 'facility_address'].astype(str).str.strip()

    # 3) facility_address method: facility_address + city + state
    mask3 = query.isna() & (df['match_method'] == 'facility_address') & has_fac_addr & has_city & has_state
    if city_col_old and city_col_old in df.columns:
        query.loc[mask3] = (
            df.loc[mask3, 'facility_address'].astype(str).str.strip() + ', ' +
            df.loc[mask3, city_col_old].astype(str).str.strip() + ', ' +
            df.loc[mask3, 'state_abbrev'].astype(str).str.strip()
        )

    # 4) none method: city + state
    mask4 = query.isna() & (df['match_method'] == 'none') & has_city & has_state
    if city_col_old and city_col_old in df.columns:
        query.loc[mask4] = (
            df.loc[mask4, city_col_old].astype(str).str.strip() + ', ' +
            df.loc[mask4, 'state_abbrev'].astype(str).str.strip()
        )

    df['geocode_query'] = query
    valid_query = _has_text(df['geocode_query'])
    unique_queries = sorted(df.loc[valid_query, 'geocode_query'].dropna().astype(str).str.strip().unique().tolist())

    if not unique_queries:
        print("  (No eligible rows for geocoding)")
        return df

    if os.path.exists(cache_path):
        cache_df = pd.read_csv(cache_path)
        if not {'address_column', 'latitude', 'longitude'}.issubset(cache_df.columns):
            cache_df = pd.DataFrame(columns=['address_column', 'latitude', 'longitude'])
    else:
        cache_df = pd.DataFrame(columns=['address_column', 'latitude', 'longitude'])

    cache_df['address_column'] = cache_df['address_column'].astype(str).str.strip()
    cache_df['latitude'] = pd.to_numeric(cache_df['latitude'], errors='coerce')
    cache_df['longitude'] = pd.to_numeric(cache_df['longitude'], errors='coerce')
    cache_map = dict(zip(cache_df['address_column'], zip(cache_df['latitude'], cache_df['longitude'])))

    def geocode_arcgis_once(address):
        delay = base_delay
        geolocator = ArcGIS(timeout=geocoder_timeout)
        for attempt in range(max_retries):
            try:
                loc = geolocator.geocode(address, exactly_one=True, timeout=geocoder_timeout)
                if loc:
                    return (loc.latitude, loc.longitude)
            except (GeocoderTimedOut, GeocoderUnavailable, Exception):
                pass
            if attempt < max_retries - 1:
                time.sleep(delay)
                delay = min(delay * 2, 20)
        return (None, None)

    def geocode_nominatim_once(address):
        delay = base_delay
        geolocator = Nominatim(user_agent=nominatim_user_agent, timeout=geocoder_timeout)
        for attempt in range(max_retries):
            try:
                loc = geolocator.geocode(address, exactly_one=True, timeout=geocoder_timeout)
                if loc:
                    return (loc.latitude, loc.longitude)
            except (GeocoderTimedOut, GeocoderUnavailable, Exception):
                pass
            if attempt < max_retries - 1:
                time.sleep(delay)
                delay = min(delay * 2, 20)
        return (None, None)

    # Only geocode addresses that are missing valid cached coordinates.
    to_arcgis = []
    for addr in unique_queries:
        cached = cache_map.get(addr)
        if cached and pd.notna(cached[0]) and pd.notna(cached[1]):
            continue
        to_arcgis.append(addr)

    updates = []
    geocoded_new = 0

    # Phase 1: ArcGIS in parallel
    arcgis_results = {}
    if to_arcgis:
        print(f"  ArcGIS geocoding {len(to_arcgis)} address queries with {arcgis_workers} worker(s)...")
        with ThreadPoolExecutor(max_workers=max(1, arcgis_workers)) as executor:
            future_to_addr = {executor.submit(geocode_arcgis_once, addr): addr for addr in to_arcgis}
            for future in as_completed(future_to_addr):
                addr = future_to_addr[future]
                try:
                    arcgis_results[addr] = future.result()
                except Exception:
                    arcgis_results[addr] = (None, None)
    else:
        print("  ArcGIS geocoding skipped (all queries already cached).")

    for addr, (lat, lon) in arcgis_results.items():
        updates.append({'address_column': addr, 'latitude': lat, 'longitude': lon})
        if lat is not None and lon is not None:
            geocoded_new += 1

    # Phase 2: Nominatim sequential fallback only for unresolved ArcGIS addresses
    to_nominatim = [
        addr for addr, (lat, lon) in arcgis_results.items()
        if lat is None or lon is None
    ]

    if to_nominatim:
        print(f"  Nominatim fallback for {len(to_nominatim)} unresolved query(ies)...")
        for addr in to_nominatim:
            lat, lon = geocode_nominatim_once(addr)
            updates.append({'address_column': addr, 'latitude': lat, 'longitude': lon})
            if lat is not None and lon is not None:
                geocoded_new += 1
            # Respect public Nominatim usage limits.
            time.sleep(max(0.0, nominatim_min_delay))

    if updates:
        cache_df = pd.concat([cache_df, pd.DataFrame(updates)], ignore_index=True)
        cache_df = cache_df.drop_duplicates(subset=['address_column'], keep='last')
        cache_df.to_csv(cache_path, index=False)

    result_map = dict(zip(cache_df['address_column'], zip(cache_df['latitude'], cache_df['longitude'])))
    df.loc[valid_query, 'latitude'] = df.loc[valid_query, 'geocode_query'].map(lambda x: result_map.get(str(x).strip(), (pd.NA, pd.NA))[0])
    df.loc[valid_query, 'longitude'] = df.loc[valid_query, 'geocode_query'].map(lambda x: result_map.get(str(x).strip(), (pd.NA, pd.NA))[1])

    resolved = int(df['latitude'].notna().sum())
    print(f"  ✓ Geocoding complete: {resolved}/{len(df)} rows have latitude/longitude ({geocoded_new} newly geocoded or refreshed)")
    return df



###-------- SECTION 1: Main Processing Pipeline --------###

def process_mortality_data(config, sex_mapping, race_mapping):
    """
    Main entry point. Processes mortality data and links to HIFLD.

    Parameters:
    -----------
    config : dict
        Configuration dictionary with file paths and column mappings
    sex_mapping, race_mapping : dict
        Standardization dictionaries

    Returns:
    --------
    df : DataFrame
        Processed mortality data with HIFLD linkages and standardized columns
    """

    print("=" * 70)
    print("MORTALITY DATA PROCESSING PIPELINE")
    print("=" * 70)

    # STEP 1: Load data
    print("\n[STEP 1] Loading data...")
    mortality_df = pd.read_csv(config["mortality_path"], low_memory=False)
    hifld_df = pd.read_csv(config["hifld_path"], low_memory=False)
    df = mortality_df.copy()

    # Rename original columns to avoid duplicates
    original_cols = df.columns.tolist()
    for col in original_cols:
        df.rename(columns={col: 'old_' + col.lower()}, inplace=True)

    print(f"  Mortality records loaded: {len(df)}")
    print(f"  HIFLD facilities loaded: {len(hifld_df)}")

    # STEP 2: Validate required columns
    print("\n[STEP 2] Validating required columns...")
    required = []

    # State is always required
    state_col = get_old_col(config.get("state_col"))
    required.append(state_col)

    # At least one facility column is required
    facility_cols_old = get_config_old_cols(config, 'facility_cols')

    # Death date can be direct or via components
    death_date_col = get_old_col(config.get("death_date_col"))
    if death_date_col and death_date_col in df.columns:
        required.append(death_date_col)
    else:
        # ensure split death date exists
        year_col = get_old_col(config.get("death_year_col"))
        month_col = get_old_col(config.get("death_month_col"))
        day_col = get_old_col(config.get("death_day_col"))
        if not (year_col in df.columns and month_col in df.columns and day_col in df.columns):
            raise ValueError(
                "ERROR: Need either death_date_col present or death_year/month/day columns present."
            )

    missing = [c for c in required if c and c not in df.columns]
    if missing:
        raise ValueError(f"ERROR: Required column(s) missing from data: {missing}")

    # Check at least one facility column exists
    facility_cols_present = [col for col in facility_cols_old if col in df.columns]
    if not facility_cols_present:
        raise ValueError(f"ERROR: At least one facility column from {facility_cols_old} must exist in data")

    address_col = get_old_col(config.get("address_col"))
    if config.get("address_col") and address_col not in df.columns:
        raise ValueError(f"ERROR: Specified address_col '{config['address_col']}' not found")
    print("  ✓ All required columns present")

    # STEP 3: Normalize state abbreviations (REQUIRED)
    print("\n[STEP 3] Normalizing state abbreviations...")
    state_col = get_old_col(config['state_col'])
    df['state_abbrev'] = df[state_col].apply(normalize_state_abbrev)
    invalid_states = df[df['state_abbrev'].isna()]
    if len(invalid_states) > 0:
        print(f"  WARNING: {len(invalid_states)} rows with unrecognized state values")
        print(f"  Sample invalid values: {invalid_states[state_col].head(3).tolist()}")
    df = df[df['state_abbrev'].notna()]
    print(f"  ✓ Processed to {len(df)} records with valid state abbreviations")

    # STEP 4: Parse death dates
    print("\n[STEP 4] Parsing death dates...")
    hifld_df['FACILITYID'] = hifld_df['FACILITYID'].astype(str)  # ensure string for later joins

    df['death_date_dt'] = pd.NaT

    # 4a) Try provided death_date_col first
    death_date_col = get_old_col(config.get('death_date_col'))
    if death_date_col and death_date_col in df.columns:
        df['death_date_dt'] = df[death_date_col].apply(
            lambda x: parse_death_date_auto(x, date_role='event')
        )

    # 4b) If still missing or no direct date column, try split component fields
    if df['death_date_dt'].isna().any():
        comp_dates = parse_date_from_components(
            df,
            get_old_col(config.get('death_year_col','')),
            get_old_col(config.get('death_month_col','')),
            get_old_col(config.get('death_day_col',''))
        )
        df['death_date_dt'] = df['death_date_dt'].fillna(comp_dates)

    failed_dates = df[df['death_date_dt'].isna()]
    print(f"  Parsed: {len(df) - len(failed_dates)}/{len(df)} dates")
    if len(failed_dates) > 0:
        print(f"  WARNING: {len(failed_dates)} rows with unparseable dates")

    # Exclude rows with missing death dates
    df = df[df['death_date_dt'].notna()]
    print(f"  ✓ Excluded {len(failed_dates)} rows with missing death dates; remaining: {len(df)}")

    # Death date parse-quality summary
    death_years = df['death_date_dt'].dt.year
    n_before_1950 = int((death_years < 1950).sum())
    n_after_2000 = int((death_years >= 2000).sum())
    n_between = int(((death_years >= 1950) & (death_years < 2000)).sum())
    print(f"  Date quality — before 1950: {n_before_1950}, 1950–1999: {n_between}, 2000+: {n_after_2000}")
    if n_before_1950 > 0:
        suspicious_years = death_years[death_years < 1950].value_counts().sort_index()
        print(f"  WARNING: {n_before_1950} death dates before 1950 — possible century drift: {suspicious_years.to_dict()}")

    # STEP 5: Build unified cause_of_death from existing text cause and decoded cause keys.
    print("\n[STEP 5] Building cause_of_death...")
    cause_key_col = get_old_col(config.get('cause_key_col'))
    source_cause_col = get_old_col(config.get('cause_col'))
    unified_cause_col = 'cause_of_death'

    if unified_cause_col not in df.columns:
        df[unified_cause_col] = pd.Series([None] * len(df), dtype='object')
    else:
        df[unified_cause_col] = df[unified_cause_col].astype('object')

    # Seed unified cause with any existing text cause values.
    if source_cause_col and source_cause_col in df.columns:
        source_vals = df[source_cause_col]
        source_nonempty_mask = source_vals.notna() & source_vals.astype(str).str.strip().ne('')
        df.loc[source_nonempty_mask, unified_cause_col] = source_vals[source_nonempty_mask]

    if cause_key_col and cause_key_col in df.columns:
        decoded_count = 0
        global_cause_dict = get_cause_dict(config)

        if global_cause_dict:
            mapped = df[cause_key_col].map(global_cause_dict)
            mapped_mask = mapped.notna()
            if mapped_mask.any():
                df.loc[mapped_mask, unified_cause_col] = mapped[mapped_mask]
                decoded_count = int(mapped_mask.sum())
            print(f"  ✓ Decoded {decoded_count} cause keys using dataset-wide dictionary '{config.get('cause_dict_name')}'")
        else:
            mapped_any_mask = pd.Series(False, index=df.index)
            for state in sorted(set(df['state_abbrev'].dropna())):
                state_cause_dict = get_cause_dict(config, state)
                if state_cause_dict:
                    state_mask = (df['state_abbrev'] == state)
                    mapped = df.loc[state_mask, cause_key_col].map(state_cause_dict)
                    mapped_mask = mapped.notna()
                    if mapped_mask.any():
                        target_idx = mapped.index[mapped_mask]
                        df.loc[target_idx, unified_cause_col] = mapped[mapped_mask]
                        mapped_any_mask.loc[target_idx] = True
            decoded_count = int(mapped_any_mask.sum())
            if decoded_count > 0:
                print(f"  ✓ Decoded {decoded_count} cause keys where state-specific dictionaries were available")
            else:
                print("  (No applicable cause dictionary found; kept existing text cause values)")
    else:
        print("  (No cause_key_col specified; using existing text cause values only)")

    # STEP 6: Normalize facility names
    print("\n[STEP 6] Normalizing facility names...")
    facility_cols_old = get_config_old_cols(config, 'facility_cols', df.columns)

    # Consolidate facility columns: use first non-null value in priority order
    df['facility_name'] = ''
    for col in facility_cols_old:
        if col in df.columns:
            mask = (df['facility_name'] == '') | (df['facility_name'].isna())
            df.loc[mask, 'facility_name'] = df.loc[mask, col].astype('string').fillna('')

    df['facility_name'] = df['facility_name'].fillna('').astype(str).str.strip()
    df['facility_name_upper'] = df['facility_name'].str.upper().fillna('')

    # Initialize output columns and preserve object/string dtype for text columns
    for col in ['hifld_name', 'hifld_address', 'hifld_city', 'facility_address']:
        if col not in df.columns:
            df[col] = pd.Series([None] * len(df), dtype='object')
        else:
            df[col] = df[col].astype('object')

    if 'facilityid' not in df.columns:
        df['facilityid'] = pd.Series([None] * len(df), dtype='object')
    else:
        df['facilityid'] = df['facilityid'].astype('object')

    if 'match_method' not in df.columns:
        df['match_method'] = 'none'
    else:
        df['match_method'] = df['match_method'].fillna('none')

    print(f"  ✓ Facility names normalized (non-empty: {(df['facility_name'] != '').sum()})")

    # STEP 7: For unmatched records with CMP_ID, try CMP-to-HIFLD join
    print("\n[STEP 7] Attempting CMP_ID-based matching for unmatched records...")
    cmp_id_col = get_old_col(config.get('cmp_id_col'))
    cmp_data_path = config.get('cmp_data_path')
    if cmp_id_col and cmp_id_col in df.columns and cmp_data_path:
        df = join_by_cmp_id(df, hifld_df, cmp_id_col, cmp_data_path)
    else:
        print("  (No cmp_id_col or cmp_data_path specified; skipping CMP_ID matching)")

    # STEP 8: Three-stage HIFLD join (exact name → dictionary → fuzzy match)
    print("\n[STEP 8] Linking records to HIFLD facility database...")
    df = join_with_hifld(df, hifld_df, config)

    # STEP 9: For unmatched names + addresses, try address-based fuzzy matching
    print("\n[STEP 9] Attempting address-based matching for unmatched records...")
    address_col = get_old_col(config.get('address_col'))
    if address_col and address_col in df.columns:
        df = join_by_address(df, hifld_df, config, address_col)
    else:
        print("  (No address column specified; skipping address-based matching)")

    # STEP 9b: For still-unmatched rows, exact-link from already-populated facility_address.
    print("\n[STEP 9b] Exact backfill from facility_address for unmatched records...")
    df = backfill_exact_from_facility_address(df, hifld_df)

    # STEP 10: Standardize optional demographic columns
    print("\n[STEP 10] Standardizing demographic attributes...")
    standardize_demographics(df, config)

    # STEP 10b: Geocode rows using prioritized address/city fallbacks
    print("\n[STEP 10b] Geocoding records...")
    city_col_old_for_geocode = get_old_col(config.get('city_col'))
    df = geocode_records(df, config, city_col_old_for_geocode)

    # STEP 11: Output summary
    print("\n[STEP 11] Final summary...")
    total_matched = df['hifld_name'].notna().sum()
    total_records = len(df)
    print(f"  Total input records: {total_records}")
    print(f"  Linked to HIFLD: {total_matched} ({100*total_matched/total_records:.1f}%)")
    print(f"  Unlinked to HIFLD: {total_records - total_matched} ({100*(total_records-total_matched)/total_records:.1f}%)")

    # Readout: records without HIFLD linkage that still retain spatial information.
    city_col_old = get_old_col(config.get('city_col'))
    has_facility_address = pd.Series(False, index=df.index)
    if 'facility_address' in df.columns:
        addr_series = df['facility_address'].astype(str).str.strip()
        has_facility_address = df['facility_address'].notna() & addr_series.ne('') & addr_series.str.lower().ne('nan')

    has_city_summary = pd.Series(False, index=df.index)
    if city_col_old and city_col_old in df.columns:
        city_series_summary = df[city_col_old].astype(str).str.strip()
        has_city_summary = df[city_col_old].notna() & city_series_summary.ne('') & city_series_summary.str.lower().ne('nan')

    unlinked_with_spatial_info = (df['hifld_name'].isna()) & (has_facility_address | has_city_summary)
    print(f"    Unlinked but has spatial info (address/city): {int(unlinked_with_spatial_info.sum())}")

    # Exclude rows related to executions based on unified cause_of_death after decoding
    execution_excluded = 0
    if 'cause_of_death' in df.columns:
        execution_mask = pd.Series(False, index=df.index)
        execution_mask |= df['cause_of_death'].astype(str).str.lower().str.contains('execution', na=False)

        execution_excluded = execution_mask.sum()
        df = df[~execution_mask]
        print(f"  ✓ Excluded {execution_excluded} rows related to executions; remaining: {len(df)}")

    # Prepare final DataFrame for export: keep new columns (lowercased) + optional + preserve_cols (lowercased)
    new_cols = ['state_abbrev', 'death_date_dt', 'facility_name', 'hifld_name', 'hifld_address', 'hifld_city', 'facility_address', 'facilityid', 'match_method', 'latitude', 'longitude', 'sex', 'race', 'date_of_birth', 'age', 'age_from_dates', 'cause_of_death']
    preserve_cols = [get_old_col(col) for col in config.get('preserve_cols', []) if col]
    if city_col_old and city_col_old in df.columns and city_col_old not in preserve_cols:
        preserve_cols.append(city_col_old)
    keep_cols = new_cols + preserve_cols
    keep_cols = [col for col in keep_cols if col in df.columns]  # only keep existing columns
    keep_cols = list(dict.fromkeys(keep_cols))  # remove duplicates, preserve order
    final_df = df[keep_cols].copy()

    # Rename preserve columns to lowercase
    rename_dict = {}
    for col in preserve_cols:
        if col in final_df.columns:
            rename_dict[col] = col.replace('old_', '')
    final_df.rename(columns=rename_dict, inplace=True)

    # STEP 12: Export to two sinks (linked/unlinked)
    linked_output_path = config.get('output_path_linked')
    unlinked_output_path = config.get('output_path_unlinked')

    has_link_fields = (
        final_df['hifld_address'].notna() |
        final_df['facility_address'].notna() |
        final_df['facilityid'].notna()
    )

    # If all joins fail but original city exists, still route record to linked output.
    city_col_final = city_col_old
    if city_col_final not in final_df.columns:
        # Preserve columns are renamed from old_* to unprefixed names above.
        maybe_renamed_city = city_col_old.replace('old_', '') if isinstance(city_col_old, str) else None
        if maybe_renamed_city in final_df.columns:
            city_col_final = maybe_renamed_city

    if city_col_final and city_col_final in final_df.columns:
        city_series = final_df[city_col_final].astype(str).str.strip()
        has_city = final_df[city_col_final].notna() & city_series.ne('') & city_series.str.lower().ne('nan')
    else:
        has_city = pd.Series(False, index=final_df.index)

    linked_df = final_df[has_link_fields | has_city].copy()
    unlinked_df = final_df[~(has_link_fields | has_city)].copy()

    # For unlinked data, always preserve the original facility columns, address, and cmp_id
    old_facility_cols = [get_old_col(col) for col in config.get("facility_cols", []) if col]
    old_address_col = get_old_col(config.get("address_col"))
    old_cmp_id_col = get_old_col(config.get("cmp_id_col"))
    old_city_col = get_old_col(config.get("city_col"))
    additional_cols = old_facility_cols + ([old_address_col] if old_address_col else []) + ([old_cmp_id_col] if old_cmp_id_col else []) + ([old_city_col] if old_city_col else [])

    for col in additional_cols:
        if col in df.columns and col not in unlinked_df.columns:
            unlinked_df[col] = df.loc[unlinked_df.index, col]

    # --- Column ordering for linked output ---
    # Lead columns: state_abbrev, death_date_dt, hifld_name, facility_name, hifld_address, hifld_city, city
    city_col_renamed = city_col_final.replace('old_', '') if city_col_final and city_col_final.startswith('old_') else city_col_final
    linked_lead = ['state_abbrev', 'death_date_dt', 'hifld_name', 'facility_name', 'hifld_address', 'hifld_city']
    if city_col_renamed and city_col_renamed in linked_df.columns:
        linked_lead.append(city_col_renamed)
    linked_lead = [c for c in linked_lead if c in linked_df.columns]
    linked_rest = [c for c in linked_df.columns if c not in linked_lead]
    linked_df = linked_df[linked_lead + linked_rest]

    # --- Column ordering for unlinked output ---
    # Lead columns: state_abbrev, death_date_dt, then original facility col(s)
    unlinked_fac_cols = [c.replace('old_', '') if c.startswith('old_') else c for c in old_facility_cols]
    unlinked_lead = ['state_abbrev', 'death_date_dt'] + [c for c in unlinked_fac_cols if c in unlinked_df.columns]
    unlinked_rest = [c for c in unlinked_df.columns if c not in unlinked_lead]
    unlinked_df = unlinked_df[unlinked_lead + unlinked_rest]

    for path, subset in [(linked_output_path, linked_df), (unlinked_output_path, unlinked_df)]:
        if path:
            dirpath = os.path.dirname(path)
            if dirpath:
                os.makedirs(dirpath, exist_ok=True)
            out = subset.copy()
            if 'death_date_dt' in out.columns:
                out['death_date_dt'] = out['death_date_dt'].dt.strftime('%Y-%m-%d')
            out.to_csv(path, index=False)
            print(f"  ✓ Exported {len(subset)} rows to {path}")

    return df

def join_with_hifld(df, hifld_df, config):
    """
    Three-stage join strategy:
    1. Exact facility name match (uppercased)
    2. Dictionary-based lookup (from all_facility_dictionaries)
    3. Fuzzy string matching (for typos)
    """

    for state in sorted(set(df['state_abbrev'].dropna())):
        hifld_state = hifld_df[(hifld_df['STATE'] == state) & (hifld_df['TYPE'] == 'STATE')]
        if hifld_state.empty:
            continue

        # Build lookup dictionaries from ALL facility types in the state.
        # JOIN 1 exact-name matching uses only TYPE='STATE' (hifld_name_upper_to_name below),
        # but backfill must also reach county/local facilities that state dictionaries map to.
        hifld_all_state = hifld_df[hifld_df['STATE'] == state]
        hifld_name_to_id = pd.Series(
            hifld_all_state['FACILITYID'].values,
            index=hifld_all_state['NAME']
        ).to_dict()
        hifld_name_to_addr = pd.Series(
            hifld_all_state['ADDRESS'].values,
            index=hifld_all_state['NAME']
        ).to_dict()
        hifld_name_to_city = pd.Series(
            hifld_all_state['CITY'].values,
            index=hifld_all_state['NAME']
        ).to_dict()

        # Uppercase mapping for exact matching by normalized text (TYPE='STATE' only for JOIN 1)
        hifld_name_upper_to_name = pd.Series(
            hifld_state['NAME'].values,
            index=hifld_state['NAME'].str.upper()
        ).to_dict()

        mask = (df['state_abbrev'] == state) & (df['hifld_name'].isna())

        if not mask.any():
            continue

        # JOIN 1: Exact uppercase match against HIFLD facility names
        before = df.loc[mask, 'hifld_name'].notna().sum()
        df.loc[mask, 'hifld_name'] = df.loc[mask, 'facility_name_upper'].map(hifld_name_upper_to_name)
        matched1 = mask & df['hifld_name'].notna()
        df.loc[matched1, 'match_method'] = 'exact_name'
        backfill_hifld_cols(df, matched1, hifld_name_to_id, hifld_name_to_addr, hifld_name_to_city)
        after = df.loc[mask, 'hifld_name'].notna().sum()
        print(f"  [{state}] JOIN 1 (exact match): {after - before} added")

        # JOIN 2: Dictionary lookup
        before = df.loc[mask, 'hifld_name'].notna().sum()
        state_dict = get_state_dict(state, '_facilities')
        mask2 = (df['state_abbrev'] == state) & (df['hifld_name'].isna())

        if mask2.any() and state_dict:
            # Try the consolidated facility name and canonical uppercase, then all original facility cols
            state_dict_upper = {k.upper(): v for k, v in state_dict.items()}
            candidate_names = pd.Series(df.loc[mask2, 'facility_name'].fillna('').astype(str).str.strip())
            candidate_upper = candidate_names.str.upper()

            matched_values = candidate_names.map(state_dict).fillna(candidate_upper.map(state_dict_upper)).infer_objects(copy=False)

            original_cols = get_config_old_cols(config, 'facility_cols')

            for col in original_cols:
                if col in df.columns:
                    still_missing = matched_values.isna()
                    if not still_missing.any():
                        break
                    col_vals = df.loc[mask2, col].fillna('').astype(str).str.strip()
                    col_vals_upper = col_vals.str.upper()
                    matched_values = matched_values.fillna(col_vals.map(state_dict)).fillna(col_vals_upper.map(state_dict_upper)).infer_objects(copy=False)

            df.loc[mask2, 'hifld_name'] = matched_values

            matched2 = mask2 & df['hifld_name'].notna()
            df.loc[matched2, 'match_method'] = 'name_dict'
            backfill_hifld_cols(df, matched2, hifld_name_to_id, hifld_name_to_addr, hifld_name_to_city)

        after = df.loc[mask, 'hifld_name'].notna().sum()
        print(f"  [{state}] JOIN 2 (dict match): {after - before} added")

        # JOIN 3: Fuzzy match for typos
        before = df.loc[mask, 'hifld_name'].notna().sum()
        mask3 = (df['state_abbrev'] == state) & (df['hifld_name'].isna())

        if mask3.any() and state_dict:
            dict_keys = list(state_dict.keys())
            dict_keys_upper = {k.upper(): v for k, v in state_dict.items()}

            # Try consolidated facility_name and upper
            for idx in df[mask3].index:
                facility_name = df.at[idx, 'facility_name']
                facility_name_upper = df.at[idx, 'facility_name_upper']

                if not should_fuzzy_match_facility_token(facility_name):
                    continue

                # Try raw
                matches = get_close_matches(facility_name, dict_keys, n=1, cutoff=0.76)
                if matches:
                    df.at[idx, 'hifld_name'] = state_dict[matches[0]]
                    continue

                # Try upper (compare uppercase input against uppercase keys)
                matches = get_close_matches(facility_name_upper, list(dict_keys_upper.keys()), n=1, cutoff=0.76)
                if matches:
                    df.at[idx, 'hifld_name'] = dict_keys_upper[matches[0]]
                    continue

            # Then try individual original columns
            still_missing = mask3 & df['hifld_name'].isna()
            original_cols = get_config_old_cols(config, 'facility_cols', df.columns)

            for col in original_cols:
                if col in df.columns:
                    for idx in df[still_missing].index:
                        col_val = str(df.at[idx, col]).strip()
                        if not col_val or col_val == 'nan':
                            continue
                        if not should_fuzzy_match_facility_token(col_val):
                            continue
                        col_val_upper = col_val.upper()

                        matches = get_close_matches(col_val, dict_keys, n=1, cutoff=0.76)
                        if matches:
                            df.at[idx, 'hifld_name'] = state_dict[matches[0]]
                            continue

                        matches = get_close_matches(col_val_upper, list(dict_keys_upper.keys()), n=1, cutoff=0.76)
                        if matches:
                            df.at[idx, 'hifld_name'] = dict_keys_upper[matches[0]]
                            continue

                    still_missing = mask3 & df['hifld_name'].isna()
                    if not still_missing.any():
                        break

            matched3 = mask3 & df['hifld_name'].notna()
            df.loc[matched3, 'match_method'] = 'fuzzy_name_dict'
            backfill_hifld_cols(df, matched3, hifld_name_to_id, hifld_name_to_addr, hifld_name_to_city)

        after = df.loc[mask, 'hifld_name'].notna().sum()
        print(f"  [{state}] JOIN 3 (fuzzy match): {after - before} added")

    return df

def join_by_address(df, hifld_df, config, address_col):
    """
    Address-based join strategy for rows still unmatched after name-based joins.
    Sub-steps per state:
      9a. Exact address_col -> HIFLD ADDRESS
      9b. Exact {STATE}_addresses dict key (address_col or facility cols) -> mapped HIFLD ADDRESS
      9c. Fuzzy address_col vs {STATE}_addresses keys -> mapped HIFLD ADDRESS  (cutoff 0.75)
      9d. Fuzzy address_col directly vs HIFLD ADDRESS                          (cutoff 0.75)
      9e. Fallback: store address_col as facility_address, no HIFLD link
    """

    if not address_col:
        return df

    # Explicit preference map for ambiguous addresses shared by multiple facilities.
    # Format: {state: {normalized_address_upper: preferred_hifld_name}}
    ambiguous_address_name_preferences = {
        'TX': {
            '379 FM 2972 WEST': 'HODGE UNIT',
        }
    }

    def resolve_hifld_row(candidates, state, addr_upper, ambiguity_hits):
        """Return the best HIFLD row from candidates, applying any preference rule."""
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        preferred_name = ambiguous_address_name_preferences.get(state, {}).get(addr_upper)
        if preferred_name:
            preferred_upper = preferred_name.strip().upper()
            for c in candidates:
                if str(c.get('NAME', '')).strip().upper() == preferred_upper:
                    ambiguity_hits[(addr_upper, preferred_upper)] = (
                        ambiguity_hits.get((addr_upper, preferred_upper), 0) + 1
                    )
                    return c
        return candidates[0]

    def do_backfill(df, idx, row, method):
        df.at[idx, 'facilityid'] = row['FACILITYID']
        df.at[idx, 'hifld_name'] = row['NAME']
        df.at[idx, 'hifld_address'] = row['ADDRESS']
        df.at[idx, 'hifld_city'] = row['CITY']
        df.at[idx, 'match_method'] = method

    # Facility columns from config (used in 9b to supplement address_col)
    facility_cols_old = get_config_old_cols(config, 'facility_cols', df.columns)

    for state in sorted(set(df['state_abbrev'].dropna())):
        hifld_state = hifld_df[(hifld_df['STATE'] == state) & (hifld_df['TYPE'] == 'STATE')].copy()
        if hifld_state.empty:
            continue

        if not ((df['state_abbrev'] == state) & (df['hifld_name'].isna())).any():
            continue

        # Build HIFLD ADDRESS -> [rows] index (ADDRESS only, not ADDRESS+CITY)
        hifld_addr_upper_to_rows = {}
        for _, row in hifld_state.iterrows():
            if not pd.notna(row['ADDRESS']) or not str(row['ADDRESS']).strip():
                continue
            key = str(row['ADDRESS']).strip().upper()
            hifld_addr_upper_to_rows.setdefault(key, []).append(row)
        hifld_address_keys = list(hifld_addr_upper_to_rows.keys())

        # Load and normalize state address dict (if any)
        state_addresses = get_state_dict(state, '_addresses')
        normalized_state_addresses = {}
        if state_addresses:
            normalized_state_addresses = {
                str(k).strip().upper(): str(v).strip()
                for k, v in state_addresses.items()
                if pd.notna(k) and pd.notna(v) and str(k).strip() and str(v).strip()
            }
        dict_keys_list = list(normalized_state_addresses.keys())

        ambiguity_hits = {}

        def current_mask(require_address=False, require_facility_address_missing=False):
            mask = (df['state_abbrev'] == state) & (df['hifld_name'].isna())
            if require_address:
                mask &= df[address_col].notna()
            if require_facility_address_missing:
                mask &= df['facility_address'].isna()
            return mask

        # ── 9a: Exact address_col -> HIFLD ADDRESS ────────────────────────────
        mask_unmatched = current_mask(require_address=True)
        added_9a = 0
        for idx in df[mask_unmatched].index:
            val = df.at[idx, address_col]
            upper = str(val).strip().upper()
            if not upper or upper == 'NAN':
                continue
            candidates = hifld_addr_upper_to_rows.get(upper, [])
            if candidates:
                do_backfill(df, idx, resolve_hifld_row(candidates, state, upper, ambiguity_hits), 'exact_address')
                added_9a += 1
        print(f"  [{state}] 9a exact address: {added_9a} added")

        # ── 9b: Exact dict key -> mapped HIFLD ADDRESS ────────────────────────
        mask_unmatched = current_mask()
        linked_9b = 0
        no_hifld_count = 0
        if normalized_state_addresses and mask_unmatched.any():
            for idx in df[mask_unmatched].index:
                candidate_keys = []
                val = df.at[idx, address_col]
                if pd.notna(val):
                    k = str(val).strip().upper()
                    if k and k != 'NAN':
                        candidate_keys.append(k)
                for fac_col in facility_cols_old:
                    fval = df.at[idx, fac_col]
                    if pd.isna(fval):
                        continue
                    k = str(fval).strip().upper()
                    if k and k != 'NAN':
                        candidate_keys.append(k)
                mapped_addr = next(
                    (normalized_state_addresses[k] for k in candidate_keys if k in normalized_state_addresses),
                    None
                )
                if not mapped_addr:
                    continue
                mapped_upper = mapped_addr.strip().upper()
                candidates = hifld_addr_upper_to_rows.get(mapped_upper, [])
                if candidates:
                    do_backfill(df, idx, resolve_hifld_row(candidates, state, mapped_upper, ambiguity_hits), 'address_dict')
                    linked_9b += 1
                else:
                    df.at[idx, 'facility_address'] = mapped_addr
                    df.at[idx, 'match_method'] = 'address_dict_no_hifld'
                    no_hifld_count += 1
        print(f"  [{state}] 9b exact dict: {linked_9b} HIFLD-linked, {no_hifld_count} dict-only added")

        # ── 9c: Fuzzy dict keys -> mapped HIFLD ADDRESS (cutoff 0.75) ─────────
        mask_unmatched = current_mask(require_address=True, require_facility_address_missing=True)
        added_9c = 0
        if normalized_state_addresses and dict_keys_list and mask_unmatched.any():
            for idx in df[mask_unmatched].index:
                val = df.at[idx, address_col]
                upper = str(val).strip().upper()
                if not upper or upper == 'NAN':
                    continue
                matches = get_close_matches(upper, dict_keys_list, n=1, cutoff=0.77)
                if not matches:
                    continue
                mapped_addr = normalized_state_addresses[matches[0]]
                mapped_upper = mapped_addr.strip().upper()
                candidates = hifld_addr_upper_to_rows.get(mapped_upper, [])
                if candidates:
                    do_backfill(df, idx, resolve_hifld_row(candidates, state, mapped_upper, ambiguity_hits), 'fuzzy_address_dict')
                    # Preserve original raw address for post-hoc fuzzy-match auditing.
                    df.at[idx, 'facility_address'] = str(val).strip()
                    added_9c += 1
        print(f"  [{state}] 9c fuzzy dict: {added_9c} added")

        # ── 9d: Fuzzy address_col -> HIFLD ADDRESS (cutoff 0.75) ─────────────
        mask_unmatched = current_mask(require_address=True, require_facility_address_missing=True)
        added_9d = 0
        if hifld_address_keys and mask_unmatched.any():
            for idx in df[mask_unmatched].index:
                val = df.at[idx, address_col]
                upper = str(val).strip().upper()
                if not upper or upper == 'NAN':
                    continue
                matches = get_close_matches(upper, hifld_address_keys, n=1, cutoff=0.77)
                if matches:
                    candidates = hifld_addr_upper_to_rows.get(matches[0], [])
                    if candidates:
                        do_backfill(df, idx, resolve_hifld_row(candidates, state, matches[0], ambiguity_hits), 'fuzzy_address')
                        # Preserve original raw address for post-hoc fuzzy-match auditing.
                        df.at[idx, 'facility_address'] = str(val).strip()
                        added_9d += 1
        print(f"  [{state}] 9d fuzzy HIFLD address: {added_9d} added")

        # ── 9e: Fallback – store raw address, no HIFLD link ──────────────────
        mask_fallback = current_mask(require_address=True, require_facility_address_missing=True)
        for idx in df[mask_fallback].index:
            val = df.at[idx, address_col]
            addr_str = str(val).strip()
            if not addr_str or addr_str.lower() == 'nan':
                continue
            df.at[idx, 'facility_address'] = addr_str
            df.at[idx, 'match_method'] = 'facility_address'

        if ambiguity_hits:
            for (addr_key, preferred_name), count in sorted(ambiguity_hits.items()):
                cand_names = sorted({
                    str(c.get('NAME', '')).strip().upper()
                    for c in hifld_addr_upper_to_rows.get(addr_key, [])
                    if str(c.get('NAME', '')).strip()
                })
                print(
                    f"  [{state}] Ambiguous address preference applied: "
                    f"{addr_key} -> {preferred_name} ({count} records); "
                    f"candidates=[{', '.join(cand_names) or 'UNKNOWN'}]"
                )

    return df


def backfill_exact_from_facility_address(df, hifld_df):
    """
    For rows still unmatched to HIFLD, attempt exact match from facility_address -> HIFLD ADDRESS
    within the same state. This catches records that already have a clean facility_address value
    (e.g., '264 FM 3478') but were not linked earlier in the pipeline.
    """

    if 'facility_address' not in df.columns:
        print("  (No facility_address column; skipping exact facility_address backfill)")
        return df

    total_added = 0

    for state in sorted(set(df['state_abbrev'].dropna())):
        hifld_state = hifld_df[(hifld_df['STATE'] == state) & (hifld_df['TYPE'] == 'STATE')].copy()
        if hifld_state.empty:
            continue

        # Use first row for duplicate addresses (same behavior as dict lookup elsewhere unless
        # explicit ambiguity rules are applied upstream).
        hifld_addr_to_row = {}
        for _, row in hifld_state.iterrows():
            if not pd.notna(row['ADDRESS']) or not str(row['ADDRESS']).strip():
                continue
            key = str(row['ADDRESS']).strip().upper()
            hifld_addr_to_row.setdefault(key, row)

        mask = (
            (df['state_abbrev'] == state)
            & (df['hifld_name'].isna())
            & (df['facility_address'].notna())
        )

        if not mask.any():
            continue

        added_state = 0
        for idx in df[mask].index:
            addr = str(df.at[idx, 'facility_address']).strip()
            if not addr or addr.lower() == 'nan':
                continue

            row = hifld_addr_to_row.get(addr.upper())
            if row is None:
                continue

            df.at[idx, 'facilityid'] = row['FACILITYID']
            df.at[idx, 'hifld_name'] = row['NAME']
            df.at[idx, 'hifld_address'] = row['ADDRESS']
            df.at[idx, 'hifld_city'] = row['CITY']
            if str(df.at[idx, 'match_method']) in ('none', 'facility_address', 'address_dict_no_hifld'):
                df.at[idx, 'match_method'] = 'facility_address_exact'
            added_state += 1

        if added_state:
            print(f"  [{state}] Exact backfill from facility_address: {added_state} added")
            total_added += added_state

    if total_added == 0:
        print("  (No exact facility_address backfills found)")

    return df

def join_by_cmp_id(df, hifld_df, cmp_id_col, cmp_data_path):
    """
    For unmatched records with CMP_ID, join via CMP-to-HIFLD mapping.
    """
    try:
        cmp_df = pd.read_csv(cmp_data_path)
    except FileNotFoundError:
        print(f"  WARNING: CMP data file not found at {cmp_data_path}")
        return df

    def normalize_id(value):
        if pd.isna(value):
            return None
        s = str(value).strip()
        if s == '' or s.lower() == 'nan':
            return None
        # convert floats like '73.0' to '73'
        try:
            f = float(s)
            if f.is_integer():
                s = str(int(f))
        except ValueError:
            pass
        return s

    # Normalize mapping IDs
    cmp_df['CMP.ID'] = cmp_df['CMP.ID'].apply(normalize_id)
    cmp_df['HIFLD.ID'] = cmp_df['HIFLD.ID'].apply(normalize_id)

    # Create lookup dicts
    cmp_to_hifld_id = dict(zip(cmp_df['CMP.ID'], cmp_df['HIFLD.ID']))

    # Normalize hifld_df facility IDs for lookup
    hifld_df['FACILITYID'] = hifld_df['FACILITYID'].apply(normalize_id)

    # Build HIFLD id to attributes dicts
    hifld_id_to_name = dict(zip(hifld_df['FACILITYID'], hifld_df['NAME']))
    hifld_id_to_addr = dict(zip(hifld_df['FACILITYID'], hifld_df['ADDRESS']))
    hifld_id_to_city = dict(zip(hifld_df['FACILITYID'], hifld_df['CITY']))

    mask = (df['hifld_name'].isna()) & (df[cmp_id_col].notna())

    if not mask.any():
        print("  (No unmatched records with CMP_ID)")
        return df

    # Convert cmp_id values to normalized strings for mapping
    cmp_values = df.loc[mask, cmp_id_col].apply(normalize_id)
    before = df.loc[mask, 'facilityid'].notna().sum()
    df.loc[mask, 'facilityid'] = cmp_values.map(cmp_to_hifld_id)

    # Debug for unmapped CMP_IDs
    missing_cmp = cmp_values[df.loc[mask, 'facilityid'].isna()].unique()
    if len(missing_cmp) > 0:
        print(f"  WARNING: {len(missing_cmp)} CMP_ID values could not be mapped to HIFLD.ID (sample): {missing_cmp[:5].tolist()}")

    matched = mask & df['facilityid'].notna()
    df.loc[matched, 'match_method'] = 'cmp_id'
    df.loc[matched, 'hifld_name'] = df.loc[matched, 'facilityid'].map(hifld_id_to_name)
    df.loc[matched, 'hifld_address'] = df.loc[matched, 'facilityid'].map(hifld_id_to_addr)
    df.loc[matched, 'hifld_city'] = df.loc[matched, 'facilityid'].map(hifld_id_to_city)

    # Debug for facilityid that did not find hifld metadata
    missing_meta = matched & df['hifld_name'].isna()
    if missing_meta.any():
        sample_ids = df.loc[missing_meta, 'facilityid'].unique()[:5]
        print(f"  WARNING: {missing_meta.sum()} matched CMP_ID rows had facilityid but no hifld_name lookup for FACILITYID sample: {sample_ids.tolist()}")

    after = df.loc[mask, 'facilityid'].notna().sum()
    print(f"  CMP_ID match: {after - before} added")

    return df

def standardize_demographics(df, config):
    """Standardize optional demographic columns."""

    # Sex/Gender
    sex_cols_config = config.get('sex_col')
    if sex_cols_config:
        if not isinstance(sex_cols_config, list):
            sex_cols_config = [sex_cols_config]

        sex_cols_old = [get_old_col(col) for col in sex_cols_config if get_old_col(col) in df.columns]

        if sex_cols_old:
            sex_source = pd.Series([None] * len(df), index=df.index, dtype='object')
            for col in sex_cols_old:
                col_vals = df[col]
                valid_mask = col_vals.notna() & col_vals.astype(str).str.strip().ne('') & col_vals.astype(str).str.lower().ne('nan')
                fill_mask = sex_source.isna() & valid_mask
                if fill_mask.any():
                    sex_source.loc[fill_mask] = col_vals.loc[fill_mask]

            df['sex'] = sex_source.apply(standardize_sex)
            print(f"  ✓ Sex standardized from {sex_cols_old}: {df['sex'].notna().sum()} values")
        else:
            print("  (No configured sex_col columns found; skipping sex standardization)")

    # Race
    race_col = get_old_col(config.get('race_col'))
    if config.get('race_col') and race_col in df.columns:
        df['race'] = df[race_col].apply(lambda x: standardize_race(x))
        raw_race = df[race_col]
        raw_race_nonempty = raw_race.notna() & raw_race.astype(str).str.strip().ne('') & raw_race.astype(str).str.lower().ne('nan')
        unmapped_race = raw_race_nonempty & df['race'].isna()
        if unmapped_race.any():
            print(f"  WARNING: {int(unmapped_race.sum())} race values could not be mapped and were set to NaN")
            unmapped_examples = (
                raw_race[unmapped_race]
                .astype(str)
                .str.strip()
                .value_counts(dropna=False)
                .head(10)
                .to_dict()
            )
            print(f"  Unmapped race examples (top 10): {unmapped_examples}")
        print(f"  ✓ Race standardized: {df['race'].notna().sum()} values")

    # Date of birth: direct column and fallback component columns
    dob_col = get_old_col(config.get('dob_col'))
    if config.get('dob_col') and dob_col in df.columns:
        # For DOB parsing, use death_date_dt as reference to properly validate century assignment
        df['date_of_birth'] = df.apply(
            lambda row: parse_death_date_auto(
                row[dob_col],
                reference_date=row.get('death_date_dt'),
                date_role='birth'
            ) if pd.notna(row.get('death_date_dt')) else parse_death_date_auto(row[dob_col], date_role='birth'),
            axis=1
        )
    else:
        df['date_of_birth'] = pd.NaT

    # Try reading birth date from split components if missing
    missing_dob = df['date_of_birth'].isna()
    if missing_dob.any():
        comp_dob = parse_date_from_components(
            df,
            get_old_col(config.get('dob_year_col','')),
            get_old_col(config.get('dob_month_col','')),
            get_old_col(config.get('dob_day_col',''))
        )
        df.loc[missing_dob, 'date_of_birth'] = comp_dob.loc[missing_dob]

    print(f"  ✓ Date of birth parsed: {df['date_of_birth'].notna().sum()} values")

    # DOB parse-quality summary
    dob_years = df['date_of_birth'].dt.year
    n_dob_before_1900 = int((dob_years < 1900).sum())
    n_dob_after_2000 = int((dob_years >= 2000).sum())
    n_dob_plausible = int(((dob_years >= 1900) & (dob_years < 2000)).sum())
    print(f"  DOB quality — before 1900: {n_dob_before_1900}, 1900–1999: {n_dob_plausible}, 2000+: {n_dob_after_2000}")
    if n_dob_before_1900 > 0:
        suspicious_dob = dob_years[dob_years < 1900].value_counts().sort_index()
        print(f"  WARNING: {n_dob_before_1900} birth dates before 1900 — possible century drift: {suspicious_dob.to_dict()}")
    if n_dob_after_2000 > 0:
        suspicious_dob_future = dob_years[dob_years >= 2000].value_counts().sort_index()
        print(f"  WARNING: {n_dob_after_2000} birth dates in 2000+ — possible century drift: {suspicious_dob_future.to_dict()}")

    # Age from provided column (optional)
    if 'age_from_dates' not in df.columns:
        df['age_from_dates'] = False
    else:
        df['age_from_dates'] = False

    age_col = get_old_col(config.get('age_col'))
    if config.get('age_col') and age_col in df.columns:
        df['age'] = pd.to_numeric(df[age_col], errors='coerce')
        invalid_age = df['age'].notna() & (df['age'] <= 0)
        if invalid_age.any():
            print(f"  WARNING: {int(invalid_age.sum())} age values ≤ 0 replaced with NaN")
            df.loc[invalid_age, 'age'] = np.nan
        age_from_col = df['age'].notna().sum()
        print(f"  ✓ Age from age_col: {age_from_col} values")
    else:
        df['age'] = np.nan

    # Compute age from death_date_dt and date_of_birth for records missing age
    if 'death_date_dt' in df.columns and 'date_of_birth' in df.columns:
        missing_age = df['age'].isna()
        valid_age = missing_age & (df['death_date_dt'].notna() & df['date_of_birth'].notna())
        if valid_age.any():
            computed = (
                (df.loc[valid_age, 'death_date_dt'] - df.loc[valid_age, 'date_of_birth']).dt.days // 365
            ).astype('Int64')
            invalid_computed = computed <= 0
            if invalid_computed.any():
                print(f"  WARNING: {int(invalid_computed.sum())} computed ages ≤ 0 (likely DOB/death date mismatch) replaced with NaN")
                computed[invalid_computed] = pd.NA
            df.loc[valid_age, 'age'] = computed
            df.loc[computed[computed.notna()].index, 'age_from_dates'] = True
            age_from_dates = df.loc[valid_age, 'age'].notna().sum()
            print(f"  ✓ Age from dates (backfill): {age_from_dates} values")
            total_age = df['age'].notna().sum()
            print(f"  ✓ Total age values available: {total_age}")

###-------- EXECUTION --------###

if __name__ == "__main__":
    df = process_mortality_data(config, sex_mapping, race_mapping)
    print("\n" + "=" * 70)
    print("Processing complete. Results available in df variable.")
    print("=" * 70)
