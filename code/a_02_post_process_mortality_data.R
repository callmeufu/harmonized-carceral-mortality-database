# This script combines all mortality data processed in a_01_mortality_processing_template;
# The output of that script is in a_01_mortality_data_processed. This script does some post-processing,
# specifically renaming and reordering of columns, before being used in 'b_01_adapted_algorithm.Rmd'

# 0. Declare root directory and load essential stuff
project.folder <- paste0(print(here::here()), "/")
mortality.data.folder <- paste0(project.folder, "data", "/a_01_mortality_data_processed")
mortality.data.post.processed.folder <- paste0(project.folder, "data", "/a_02_mortality_data_post_processed/")
library(purrr)
library(dplyr)
library(lubridate)

# 1. Load mortality-exposure datasets for all years
message("Loading mortality-temperature dataset(s)")

csv_files <- list.files(
  path = file.path(mortality.data.folder),
  pattern = "\\.csv$",
  full.names = TRUE
)

if (length(csv_files) == 0) {
  stop("No CSV files found in directory.")
}

df <- map_dfr(csv_files, ~ {
  read_csv(.x) %>%
    mutate(across(everything(), as.character))
})

# 2. Clean up the data

df <- df %>%
  filter(city != "NONE" | is.na(city)) %>% # an empty city entry for TX should have been excluded but was geocoded by error in a_01_mortality_processing_template
  rename(hifld_facility_id = facilityid) %>%
  rename(cause_general = cause_of_death) %>%
  mutate(state_index = as.integer(factor(state_abbrev))) %>% # Convert the state_abbrev string column to a numeric index
  mutate(death_month = month(death_date_dt)) %>%
  mutate(year = year(death_date_dt))

new_order <- c(
    "death_date_dt",
    "year",
    "death_month",
    "state_abbrev",
    "state_index",
    "latitude",
    "longitude",
    "match_method",
    "hifld_facility_id",
    "hifld_name",
    "hifld_address",
    "hifld_city",
    "facility_name",
    "facility_address",
    "place",
    "city",
    "location",
    "incident_location",
    "sex",
    "race",
    "date_of_birth",
    "age",
    "age_from_dates",
    "cause_general",
    "cause_specific",
    "illspec",
    "drugspec",
    "selfspec",
    "accspec",
    "suicspec",
    "homispec",
    "otherspec",
    "medical_cause",
    "days_incarcerated",
    "date_incarcerated"
  )

combined_mortality_data <- df[, new_order]

saveRDS(combined_mortality_data, paste0(mortality.data.post.processed.folder, "combined_mortality_data.rds"))
