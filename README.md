# Harmonized Carceral Mortality Database (HCMD)

The Harmonized Carceral Mortality Database (HCMD) is a unified, georeferenced dataset of deaths occurring in U.S. state-operated correctional facilities. It is compiled and harmonized from multiple administrative, nonprofit, and public-records sources. The HCMD standardizes decedent characteristics, facility identifiers, dates of death, and causes of death to enable more consistent epidemiological analyses of custodial mortality in the United States, independent of federal reporting programs.

The dataset ('data/hcmd.rds') currently includes: 

- **49,682** mortality records; 85.7% (n = 42,584) have algorithmically estimated cause of death
- All 50 states have at least some records available
- Temporal coverage **March 1996 – December 2024** varies by state
- **1,089** unique carceral facilities represented

Updates will be done ~ annually in July.

## Background

Documenting and measuring mortality in correctional facilities is essential for understanding the health consequences of incarceration, identifying preventable deaths, and informing policy. Deaths in U.S. prisons rose sharply over recent decades — from 3,170 documented state prison deaths in 2001 to 6,182 in 2020 — despite a smaller prison population in the latter year.

Federal reporting has not kept pace. The Death in Custody Reporting Act (DCRA) of 2000 established the Bureau of Justice Statistics' Mortality in Correctional Institutions (MCI) program, but the DCRA expired in 2006. A reauthorized DCRA (2014) shifted collection responsibility to the Bureau of Justice Assistance (BJA), whose data collection has had significant, well-documented quality and coverage gaps, and none of which has been made publicly available. BJS's own MCI data collection ended after 2019.

In response, researchers and nonprofits — including the [UCLA Law Behind Bars Data Project](https://github.com/uclalawbehindbars), the [Third City Project]([https://github.com/uclalawbehindbars](https://3rdcityproject.com/index.php/mortality_data/)), the [Texas Justice Initiative](https://texasjusticeinitiative.org/datasets/custodial-deaths), [Incarceration Transparency](https://www.incarcerationtransparency.org/), and others — have built independent datasets to fill this gap. The HCMD extends this effort by harmonizing records across these sources, the (deprecated) federal MCI program, and state Departments of Corrections into a single, georeferenced database. We further apply Natural Language Processing (NLP) to free-text cause of death differentially reported by the sources to automate cause of death for857.7% of records (n = 42,584).

## Methods

Full methodological detail is available in the accompanying [preprint](https://doi.org/10.64898/2026.07.29.26359256). In brief:

### Data Sources

A full list of source datasets and their coverage is documented in Table 1 of our accompanying paper. Records were compiled from three main categories of sources:

1. **BJS MCI dataset** — the most authoritative source, released for all 50 states from October 2015 to December 2019 via a Freedom of Information Act (FOIA) request.
2. **State Department of Corrections (DOC) websites** — reviewed individually for publicly posted mortality records.
3. **Nonprofit and prior research datasets** — compiled from nonprofit organizations and known academic projects that rely on public records requests.

### Compilation & Deduplication
When multiple sources reported records for the same state and overlapping time period, the more "authoritative"[^1] source (state or federal government agencies) was prioritized over nonprofit or third-party compilations. Column names were standardized across all sources (e.g., decedent name, state, age, sex, death date), and death dates were split into separate year/month/day columns. Cause-of-death information, which varied widely in specificity, was split into `cause_general` and `cause_specific` fields.

[^1]: "authoritative" here does not necessarily imply accurate or truthful. We use "authoritative" to indicate the provenance of the data is closer to the source

### Facility Standardization & Geolocation
Facility names and abbreviations varied substantially both across and within sources (e.g., "Cross City C.I.", "Cross City", "CCCI"). A manually built, state-specific crosswalk dictionary (`all_facility_dictionaries.py`) maps these variants to canonical facility names and IDs from the [HIFLD Prison Boundaries](https://hifld-geoplatform.hub.arcgis.com/) dataset, the most comprehensive available source on U.S. correctional facility locations.

Records were linked to HIFLD facilities through a **scaffolded, multi-stage join**, applying successive matching strategies in order of reliability. Each record's `match_method` field documents which stage resolved it:

| Stage | `match_method` | Description |
|---|---|---|
| 1 | `cmp_id` | Pre-existing crosswalk from the UCLA Law Behind Bars Data Project |
| 2 | `exact_name` | Exact match on facility name against HIFLD `NAME` (state-operated facilities only) |
| 3 | `exact_dict` | Match via the facility-name crosswalk dictionary |
| 4 | `fuzzy_name_dict` | Fuzzy match (0.76 similarity cutoff) against dictionary keys |
| 5 | `exact_address` | Exact match on address against HIFLD `ADDRESS` |
| 6 | `address_dict` | Match via an address crosswalk dictionary |
| 7 | `fuzzy_address_dict` | Fuzzy match against address dictionary keys |
| 8 | `fuzzy_address` | Fuzzy match directly against HIFLD addresses |
| — | `address_dict_no_hifld` | Address resolved via dictionary but no corresponding HIFLD facility (often closed facilities) |
| — | `facility_address` | No dictionary or direct match; raw source address retained |
| — | `none` | No street address available (Texas only); city-level only |

Unresolved records that have address information (but could not be linked to a specific carceral facility) is available and are included in the database with reduced location precision, rather than being dropped.

### Geocoding
Records were geocoded using `geopy`, querying ArcGIS's World Geocoding service first and falling back sequentially to Nominatim (OpenStreetMap) for unresolved records. Query precision (full facility address vs. city/state only) was determined by each record's `match_method`.

### Categorical Standardization
Standardized dictionaries were built to harmonize inconsistent source values for sex and race/ethnicity. Age was computed from date of birth and date of death when both were available (`age_from_dates`), supplementing reported age where present.

### Cause of Death Coding
Free-text and categorical cause-of-death fields were processed using a keyword-matching algorithm adapted from McCord et al. (2025), extended with carceral-specific terminology (e.g., additional overdose-related keywords) and reviewed by a physician with experience in correctional health [UPDATE BASED ON ACTUAL VALIDATION PROTOCOL]. The algorithm assigns both a Manner of Death and a Cause of Death to each record where possible.

### Exclusions
Records were excluded from the final database if they lacked location or spatial data, lacked a recorded date of death, or represented executions rather than deaths from other causes.

## Data Dictionary

Key columns in the harmonized dataset include:

| Column | Description |
|---|---|
| `case_number` | unique identifier per decedent |
| `death_date_dt` | Date of death |
| `state_abbrev` | State postal abbreviation |
| `latitude`, `longitude` | Geocoded location of death |
| `match_method` | Method used to link the record to a HIFLD facility (see table above) |
| `hifld_facilityid` | Unique identifier for each carceral facility |
| `hifld_name` | Canonical HIFLD facility name |
| `hifld_address`, `hifld_city` | Facility location per HIFLD |
| `facility_name` | Facility name as it appeared on the *original* mortality record |
| `facility_address`, `city` | Address/city as reported on the original record |
| `sex`, `race` | Standardized decedent demographics |
| `date_of_birth`, `age`, `age_from_dates` | Decedent age (reported and/or computed) |
| `final_cause` | Algorithm-classified cause-of-death information based on `cause_general` and `cause_specific` columns|
| `class_level_1` | Broadest-level cause-of-death information |
| `class_level_2` | Intermediate-level cause-of-death information |
| `class_level_3a` | Specific cause-of-death information |
| `class_level_3b` | Accompanying specific cause-of-death information in cases with multiple specific causes of death |
| `matched_keywords` | Words that were used to classify class_level_3a and class_level_3b|
| `cause_general`, `cause_specific` | General and specific cause-of-death information |
| `illspec`, `drugspec`, `selfspec`, `accspec`, `suicspec`, `homispec`, `otherspec`, `place`, `evaluate`, `cause` | MCI codebook–defined cause-of-death detail fields |

## Usage

Users can create a personal version of `hcmd.rds` by adding their own mortality data and running the processing pipeline described below.

### 1. Add raw mortality data

Place additional mortality records in:

`data/a_00_mortality_data_raw/`

The raw mortality data are processed using:

* `code/a_00_all_facility_dictionaries.py`
* `code/a_00_configs`
* `code/a_01_mortality_processing_template.py`

### 2. Process the raw data

Once `code/a_01_mortality_processing_template.py` is run, the processed mortality data will be saved to:

`data/a_01_mortality_data_processed/`

### 3. Post-process the mortality data

The processed mortality data are then post-processed using:

`code/a_02_post_process_mortality_data`

This produces `combined_mortality_data.rds`, which is saved to:

`data/a_02_mortality_data_post_processed/`

### 4. Run the COD-standardization algorithm

`combined_mortality_data.rds` is then processed using:

`code/b_02_adapted_algorithm`

This produces the final `hcmd.rds` dataset, which is saved to:

`data/hcmd.rds`


## Known Limitations

- Facility matching relies in part on abbreviation crosswalks that could contain errors.
- Some geocoded locations refer to hospitals rather than correctional facilities (e.g., NV, WY).
- Some records list multiple facilities (KY) or both a prison and a hospital (WI).
- Louisiana's records likely include some county jail deaths alongside state prison deaths.

## Citation

If you use the HCMD in your work, please cite: https://doi.org/10.64898/2026.07.29.26359256

## License

[Specify license]

## Contact

Ufuoma Ovienmhada
ufuoma@arizona.edu
