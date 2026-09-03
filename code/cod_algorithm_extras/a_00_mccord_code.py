import pandas as pd
import numpy as np
from numpy import isnan
import math as math
import csv

# Constants
# MEO Entries
excel_file_name = 'INSERT FILLED IN TEMPLATE PATHNAME'
sub_sheet = 'DATA'
# Keywords
keywords_excel = 'INSERT KEYWORDS SHEET PATHNAME'
kw_sub_sheet = 'keywords'



# When ran
if __name__ == "__main__":
    #Coding Manners into T/F
    try:    
        #Read excel file using pandas
        df = pd.read_excel(excel_file_name, sheet_name=sub_sheet, engine='openpyxl')
        
        #Strip and lowercase Manner and Cause columns
        df['MANNER'] = df['MANNER'].str.strip().str.lower()
        df['CAUSE'] = df['CAUSE'].str.strip().str.lower()

        #Initialize manner columns
        df['ACCIDENT'] = False
        df['NATURAL'] = False
        df['HOMICIDE'] = False
        df['SUICIDE'] = False
        df['UNKNOWN'] = False
        df['PENDING'] = False

        #check for where manner = accident
        df.loc[df['MANNER'] == 'accident', 'ACCIDENT'] = True
        df.loc[df['MANNER'] == 'natural', 'NATURAL'] = True
        df.loc[df['MANNER'] == 'homicide', 'HOMICIDE'] = True
        df.loc[df['MANNER'] == 'suicide', 'SUICIDE'] = True
        df.loc[df['MANNER'] == 'unknown', 'UNKNOWN'] = True
        df.loc[df['MANNER'] == 'undetermined', 'UNKNOWN'] = True
        df.loc[df['MANNER'] == 'pending', 'PENDING'] = True

        print(df[['MANNER','ACCIDENT','NATURAL','HOMICIDE','SUICIDE','UNKNOWN']])  
    except:
        print('exception')

    #Keywords list building
    try:
        #Make lists out of each column in the keywords_excel sheet

        #Overdose keywords list
        od_keywords = pd.read_excel(keywords_excel, kw_sub_sheet, engine='openpyxl')['OVERDOSE KEYWORDS'].tolist()
        # Remove all occurrences of 'nan' from the list
        od_keywords = [x for x in od_keywords if not pd.isna(x)]
        #for elem in od_keywords:
            #print(elem)

        #Heat keywords list
        heat_keywords = pd.read_excel(keywords_excel, sheet_name='keywords', engine='openpyxl')['HEAT KEYWORDS'].tolist()
        # Remove all occurrences of 'nan' from the list
        heat_keywords = [x for x in heat_keywords if not pd.isna(x)]
        #for elem in heat_keywords:
            #print(elem)
       
        #Cold keywords list
        cold_keywords = pd.read_excel(keywords_excel, sheet_name='keywords')['COLD KEYWORDS'].tolist()
        # Remove all occurrences of 'nan' from the list
        cold_keywords = [x for x in cold_keywords if not pd.isna(x)]
        #for elem in cold_keywords:
            #print(elem)

        #Injury keywords list
        inj_keywords = pd.read_excel(keywords_excel, sheet_name='keywords')['INJURY KEYWORDS'].tolist()
        #Remove all occurrences of 'nan' from the list
        inj_keywords = [x for x in inj_keywords if not pd.isna(x)]
        #for elem in inj_keywords:
            #print(elem)        

        #Heart keywords list   
        heart_keywords = pd.read_excel(keywords_excel, sheet_name='keywords', engine='openpyxl')['HEART KEYWORDS'].tolist()
        # Remove all occurrences of 'nan' from the list
        heart_keywords = [x for x in heart_keywords if not pd.isna(x)]
        #for elem in heart_keywords:
            #print(elem)

        #Illness keywords list   
        illness_keywords = pd.read_excel(keywords_excel, sheet_name='keywords', engine='openpyxl')['ILLNESS KEYWORDS'].tolist()
        # Remove all occurrences of 'nan' from the list
        illness_keywords = [x for x in illness_keywords if not pd.isna(x)]
        #for elem in illness_keywords:
            #print(elem)

        #Undetermined keywords list   
        undetermined_keywords = pd.read_excel(keywords_excel, sheet_name='keywords', engine='openpyxl')['UNDETERMINED'].tolist()
        # Remove all occurrences of 'nan' from the list
        undetermined_keywords = [x for x in undetermined_keywords if not pd.isna(x)]
        #for elem in undetermined_keywords:
            #print(elem)

        #Firearm keywords list   
        firearm_keywords = pd.read_excel(keywords_excel, sheet_name='keywords', engine='openpyxl')['FIREARM'].tolist()
        # Remove all occurrences of 'nan' from the list
        firearm_keywords = [x for x in firearm_keywords if not pd.isna(x)]
        for elem in firearm_keywords:
            print(elem)

        #USE ANOTHER ITERATION OF THE CODE IN THIS SECTION TO READ IN THE SUDORS KEYWORDS IF DESIRED
        
    except:
        print('exception')

   #Preliminary cause assignments. 
    try:
        
        #Clean cause strings, strip of preceding/following spaces and capitalize to match kw
        df['CAUSE'] = df['CAUSE'].str.strip().str.upper()
        #print(df['CAUSE'])
        
        #Initialize preliminary cause columns
        df['PRELIM_OD'] = False
        df['PRELIM_HEAT'] = False
        df['PRELIM_COLD'] = False
        df['PRELIM_OTHER_INJURY'] = False
        df['PRELIM_HOMICIDE'] = False
        df['PRELIM_SUICIDE'] = False
        df['PRELIM_HEART'] = False
        df['PRELIM_ILLNESS'] = False
        df['PRELIM_FIREARM'] = False
        df['PRELIM_UNKNOWN'] = False

        #Overdose
        for kw in od_keywords:
            df.loc[df['CAUSE'].str.contains(kw), 'PRELIM_OD'] = True
        #print(df['PRELIM_OD'])

        #Heat
        for kw in heat_keywords:
            df.loc[df['CAUSE'].str.contains(kw), 'PRELIM_HEAT'] = True
        #print(df['PRELIM_HEAT'])
            
        #Cold
        for kw in cold_keywords:
            df.loc[df['CAUSE'].str.contains(kw), 'PRELIM_COLD'] = True
        #print(df['PRELIM_COLD'])

        #Other Injury
        for kw in inj_keywords:
            df.loc[df['CAUSE'].str.contains(kw), 'PRELIM_OTHER_INJURY'] = True
        #print(df['PRELIM_OTHER_INJURY'])

        #Homicide, only need to check if the manner = homicide
        df.loc[df['MANNER'] == 'homicide', 'PRELIM_HOMICIDE'] = True
        #print(df['PRELIM_HOMICIDE'])

        #Suicide, only need to check if the manner = suicide
        df.loc[df['MANNER'] == 'suicide', 'PRELIM_SUICIDE'] = True
        #print(df['PRELIM_SUICIDE'])

        #Heart
        for kw in heart_keywords:
            df.loc[df['CAUSE'].str.contains(kw), 'PRELIM_HEART'] = True
        #print(df['PRELIM_HEART'])

        #Illness
        for kw in illness_keywords:
            df.loc[df['CAUSE'].str.contains(kw), 'PRELIM_ILLNESS'] = True
        #print(df['PRELIM_ILLNESS'])

        #Firearm
        for kw in firearm_keywords:
            df.loc[df['CAUSE'].str.contains(kw), 'PRELIM_FIREARM'] = True
        #print(df['PRELIM_FIREARM'])

        #Unknown
        for kw in undetermined_keywords:
            df.loc[df['CAUSE'].str.contains(kw), 'PRELIM_UNKNOWN'] = True
        #print(df['PRELIM_UNKNOWN'])
            
        print(df)
            

    except:
            print('exception')

    #Applying logic and context of Manner to assign records final causes of death
    try:
        #Initialize final columns
        df['FINAL_ACC_OD'] = False
        df['FINAL_ALL_OD'] = False
        df['FINAL_HEAT'] = False
        df['FINAL_HEAT_UNK'] = False
        df['FINAL_COLD'] = False
        df['FINAL_COLD_UNK'] = False
        df['FINAL_OTHER_INJURY'] = False
        df['FINAL_OTHER_INJURY_UNK'] = False
        df['FINAL_HOMICIDE'] = False
        df['FINAL_SUICIDE'] = False
        df['FINAL_HEART'] = False
        df['FINAL_HEART_UNK'] = False
        df['FINAL_ILLNESS'] = False
        df['FINAL_ILLNESS_UNK'] = False
        df['FINAL_UNKNOWN'] = False
        df['FINAL_UNKNOWN_UNK'] = False
        df['MANUAL'] = False

        #Final UNINTENTIONAL overdose (only includes only overdoses with accidental manner)
        df.loc[df['ACCIDENT'] & df['PRELIM_OD'], 'FINAL_ACC_OD'] = True
        print(df['FINAL_ACC_OD'])

        #Final ALL Overdose count, includes overdoses of accidental, homicidal, suicidal, and undetermined manner
        #Specifically excludes natural manner deaths as Overdose is not a natural death
        df.loc[~df['NATURAL'] & df['PRELIM_OD'], 'FINAL_ALL_OD'] = True

        #Final heat (accident only)
        df.loc[df['ACCIDENT'] & df['PRELIM_HEAT'] & ~df['PRELIM_OD'], 'FINAL_HEAT'] = True
        print(df['FINAL_HEAT'])

        #Final heat ALLOW UNKNOWN
        df.loc[(df['ACCIDENT'] | df['UNKNOWN']) & df['PRELIM_HEAT'] & ~df['PRELIM_OD'], 'FINAL_HEAT_UNK'] = True

        #Final Cold (accident only)
        df.loc[df['ACCIDENT'] & df['PRELIM_COLD'] & ~df['PRELIM_OD'], 'FINAL_COLD'] = True

        #Final cold ALLOW UNKNOWN
        df.loc[(df['ACCIDENT'] | df['UNKNOWN']) & df['PRELIM_COLD'] & ~df['PRELIM_OD'], 'FINAL_COLD_UNK'] = True

        #Final other injury
        df.loc[df['ACCIDENT'] & df['PRELIM_OTHER_INJURY'] & ~df['PRELIM_OD'] & ~df['PRELIM_COLD'] & ~df['PRELIM_HEAT'], 'FINAL_OTHER_INJURY'] = True

        #Final other injury ALLOW UNKNOWN MANNER
        df.loc[(df['ACCIDENT'] | df['UNKNOWN']) & df['PRELIM_OTHER_INJURY' ] & ~df['PRELIM_OD'] & ~df['PRELIM_COLD'] & ~df['PRELIM_HEAT'], 'FINAL_OTHER_INJURY_UNK'] = True

        #Final homicide
        df.loc[df['PRELIM_HOMICIDE'], 'FINAL_HOMICIDE'] = True
        print(df['FINAL_HOMICIDE'])

        #Final Suicide
        df.loc[df['PRELIM_SUICIDE'], 'FINAL_SUICIDE'] = True
        print(df['FINAL_SUICIDE'])

        #Final Heart
        df.loc[df['NATURAL'] & df['PRELIM_HEART'], 'FINAL_HEART'] = True

        #Final Heart ALLOW UNKNOWN
        df.loc[(df['NATURAL'] | df['UNKNOWN']) & df['PRELIM_HEART'], 'FINAL_HEART_UNK'] = True

        #Final Illness
        df.loc[df['NATURAL'] & df['PRELIM_ILLNESS'] & ~df['PRELIM_HEART'], 'FINAL_ILLNESS'] = True

        #Final Illness ALLOW UNKNOWN
        df.loc[(df['NATURAL'] | df['UNKNOWN']) & df['PRELIM_ILLNESS'] & ~df['PRELIM_HEART'], 'FINAL_ILLNESS_UNK'] = True

        #Final Undetermined
        df.loc[df['UNKNOWN'], 'FINAL_UNKNOWN'] = True
        print(df['FINAL_UNKNOWN'])

        #Final Undetermined when undetermined manner is allowed to be coded
        df.loc[df['UNKNOWN'] & ~df['PRELIM_OD'] & ~df['FINAL_OTHER_INJURY_UNK'] & ~df['FINAL_HEART_UNK'] & ~df['FINAL_ILLNESS_UNK'], 'FINAL_UNKNOWN_UNK'] = True

        #For manual output
        df.loc[~df['FINAL_OD'] & ~df['FINAL_HEAT'] & ~df['FINAL_COLD'] & ~df['FINAL_OTHER_INJURY'] & ~df['FINAL_HOMICIDE'] & ~df['FINAL_SUICIDE'] & ~df['FINAL_HEART'] & ~df['FINAL_ILLNESS'] & ~df['FINAL_UNKNOWN'], 'MANUAL'] = True
        #df filtered for manual output
        manaual_df = df[df['MANUAL'] == True ]
        print(manaual_df)

    except:
        print('exception')

    #Assign values for mutually exclusive coding schema
    try:

        #initialize COD column
        df['COD'] = 0

        #Overdose = 1
        df.loc[df['FINAL_ACC_OD'], 'COD'] = 1

        #Heat = 2
        df.loc[df['FINAL_HEAT'], 'COD'] = 2

        #Cold = 3
        df.loc[df['FINAL_COLD'], 'COD'] = 3

        #Other Injury = 4
        df.loc[df['FINAL_OTHER_INJURY'], 'COD'] = 4

        #Homicide = 5
        df.loc[df['FINAL_HOMICIDE'], 'COD'] = 5

        #Suicide = 6
        df.loc[df['FINAL_SUICIDE'], 'COD'] = 6

        #Heart = 7
        df.loc[df['FINAL_HEART'], 'COD'] = 7

        #Illness = 8
        df.loc[df['FINAL_ILLNESS'], 'COD'] = 8

        #Unknown = 9
        df.loc[df['FINAL_UNKNOWN'], 'COD'] = 9

        #Need to be manually coded = 0
        df.loc[df['MANUAL'], 'COD'] = 0

        print(df.head)

    except:
        print('exception')

    #export the full dataframe to an excel sheet
    try:
        df.to_excel('final cod output.xlsx', index = False)
    
    except:
        print('exception')

    
