import pandas as pd
import requests
import io
import time
import re

SHEET_ID = "15v52FSkde4DJXkyie7Z0CCq1zQoT0hS0nQRXkORkONg"
CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"
MIN_THRESHOLD = 10 

def clean_handle(link, platform):
    if pd.isna(link) or str(link).strip() == "": 
        return None
    link = str(link).strip()
    
    if platform == "leetcode":
        if "leetcode.com/u/" in link:
            return link.split("leetcode.com/u/")[1].replace("/", "")
        if "LeetCode Profile" in link:
            return link.split("-")[0].strip()
            
    elif platform == "hackerrank":
        if "hackerrank.com/profile/" in link:
            return link.split("hackerrank.com/profile/")[1].replace("/", "")
        if "|" in link: 
            return link.split("|")[0].split("-")[-1].strip()
            
    return link 

def fetch_leetcode_score(username):
    if not username: return 0
    url = "https://leetcode.com/graphql/"
    query = """
    query getUserProfile($username: String!) {
      matchedUser(username: $username) {
        submitStats: submitStatsGlobal { acSubmissionNum { count } }
      }
    }
    """
    try:
        r = requests.post(url, json={"query": query, "variables": {"username": username}}, timeout=5)
        stats = r.json()['data']['matchedUser']['submitStats']['acSubmissionNum']
        return stats[0]['count'] 
    except Exception:
        return 0

def process_students():
    print("Downloading Gates_Tracker data...")
    try:
        # 1. Fetch raw CSV data text
        response = requests.get(CSV_URL)
        response.raise_for_status() # Will trigger an error if the link isn't public
        
        # 2. Dynamically find the real header row (skips "CSE-B" titles)
        lines = response.text.splitlines()
        header_idx = 0
        for i, line in enumerate(lines):
            if "Roll.No" in line and "Student Name" in line:
                header_idx = i
                break
                
        # 3. Read into pandas using the correct starting row
        df = pd.read_csv(io.StringIO(response.text), skiprows=header_idx)
        
        # Check if columns exist
        if 'Leet Code Link' not in df.columns:
            print(f"Error: Could not find 'Leet Code Link' column. Columns found: {list(df.columns)}")
            return
        
        print("Data downloaded successfully! Cleaning handles...")
        
        df['LC_Handle'] = df['Leet Code Link'].apply(lambda x: clean_handle(x, "leetcode"))
        df['HR_Handle'] = df['Hacker Rank Link'].apply(lambda x: clean_handle(x, "hackerrank"))
        df['Email'] = df['Roll.No'].apply(lambda x: f"{str(x).lower()}@gatesit.ac.in" if pd.notna(x) else None)
        
        results = []
        
        # Iterate over students
        for index, row in df.iterrows():
            roll_no = row['Roll.No']
            name = row['Student Name']
            
            # Skip empty rows or section divider rows
            if pd.isna(roll_no) or "CSE" in str(roll_no) or "Roll.No" in str(roll_no): 
                continue 
            
            print(f"Fetching stats for {name} ({roll_no})...")
            lc_score = fetch_leetcode_score(row['LC_Handle'])
            hr_score = 0 # HackerRank placeholder
            
            total_score = lc_score + hr_score
            
            results.append({
                "Roll Number": roll_no,
                "Name": name,
                "LeetCode": lc_score,
                "HackerRank": hr_score,
                "Total": total_score,
                "Email": row['Email']
            })
            
            time.sleep(1) # Crucial: Don't get IP banned by LeetCode
            
        final_df = pd.DataFrame(results)
        final_df.to_csv("processed_scores.csv", index=False)
        print(f"\nSuccess! processed_scores.csv created with {len(final_df)} students.")
        
    except Exception as e:
        print(f"\nCRITICAL ERROR: {e}")

if __name__ == "__main__":
    process_students()