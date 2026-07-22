"""
Dataset-specific configs for a_00_mortality_processing_template.py.

Add a new entry to CONFIGS to support another dataset, then set CONFIG_NAME
at the top of a_00_mortality_processing_template.py to pick it.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


STATE_DOCS_CONFIG = {
    'fuzzy_name_cutoff': 0.76,      # cutoff for facility name fuzzy matching (JOIN 3)
    'fuzzy_address_cutoff': 0.77,   # cutoff for address fuzzy matching (steps 9c and 9d)
    
    "mortality_path":       str(REPO_ROOT / "data" / "a_00_mortality_data_raw" / "combined_mortality_data_04012026.csv"),
    "hifld_path":           str(REPO_ROOT / "data" / "z_other_datasets" / "Prison_Boundaries.csv"),
    "output_path_linked":   str(REPO_ROOT / "data" / "a_01_mortality_data" / "TEST_state_docs_excl_2016_to_2019_06012026.csv"),
    "output_path_unlinked": str(REPO_ROOT / "data" / "a_01_mortality_data" / "unlinked_mortality_data" / "TEST_unlinked_state_docs_excl_2016_to_2019_06012026.csv"),

    "death_date_col": "DEATH_DATE",
    "facility_cols": ["FACILITY_NAME", "FACILITY_ABBREV"],
    "address_col": "FACILITY_ADDRESS",

    "state_col": "STATE_ABBREV",

    "death_year_col": "DEATH_YEAR",
    "death_month_col": "DEATH_MONTH",
    "death_day_col": "DEATH_DAY",

    "dob_col": "DATE_OF_BIRTH",
    "dob_year_col": "BIRTH_YEAR",
    "dob_month_col": None,
    "dob_day_col": None,

    "sex_col": ["SEX", "GENDER"],
    "race_col": "RACE",
    "age_col": "AGE",
    "cause_col": "CAUSE_GENERAL",
    "cause_key_col": "CAUSE_GENERAL_KEY",
    "cause_dict_name": None,
    "city_col": "CITY",

    "cmp_id_col": "CMP_ID",
    "cmp_data_path":        str(REPO_ROOT / "data" / "z_other_datasets" / "CMP_fac_data_UO.csv"),

    "preserve_cols": ["CAUSE_SPECIFIC", "DAYS_INCARCERATED", "DATE_INCARCERATED", "MEDICAL_CAUSE", "Location", "INCIDENT_LOCATION"],
}


MCI_CONFIG = {
    'fuzzy_name_cutoff': 0.76,      # cutoff for facility name fuzzy matching (JOIN 3)
    'fuzzy_address_cutoff': 0.77,   # cutoff for address fuzzy matching (steps 9c and 9d)
    
    "mortality_path":       str(REPO_ROOT / "data" / "a_00_mortality_data_raw" / "mciprison20160101_20191231.csv"),
    "hifld_path":           str(REPO_ROOT / "data" / "z_other_datasets" / "Prison_Boundaries.csv"),
    "output_path_linked":   str(REPO_ROOT / "data" / "a_01_mortality_data" / "TEST_mci_2016_2019_06012026.csv"),
    "output_path_unlinked": str(REPO_ROOT / "data" / "a_01_mortality_data" / "unlinked_mortality_data" / "TEST_unlinked_mci_2016_2019_06012026.csv"),

    "death_date_col": None,
    "facility_cols": ["Facname"],
    "address_col": None,

    "state_col": "State",

    "death_year_col": "Year",
    "death_month_col": "Deathmon",
    "death_day_col": "Deathday",

    "dob_col": None,
    "dob_year_col": "Dobyear",
    "dob_month_col": "Dobmon",
    "dob_day_col": "Dobday",

    "sex_col": ["Gender"],
    "race_col": "Race",
    "age_col": None,
    "cause_col": None,
    "cause_key_col": "Cause",
    "cause_dict_name": "mci_cause_dict",
    "city_col": None,

    "cmp_id_col": None,
    "cmp_data_path":        str(REPO_ROOT / "data" / "z_other_datasets" / "CMP_fac_data_UO.csv"),

    "preserve_cols": ["Illspec", "Drugspec", "Selfspec", "Accspec", "Suicspec", "Homispec", "Otherspec", "Place"],
}


CONFIGS = {
    "state_docs": STATE_DOCS_CONFIG,
    "mci": MCI_CONFIG,
}
