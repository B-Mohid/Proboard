# PROBOARD 🚀

I built PROBOARD because manually tracking coding progress for a large batch of students (130+ in this case) across different competitive programming platforms is a massive headache. Nobody wants to click through a hundred LeetCode and HackerRank profiles every week just to see who solved what. 

PROBOARD is a live, automated analytics dashboard that takes a Google Sheet (or CSV/Excel upload) of student profile links, securely fetches their real-time stats, and visualizes the data to help identify who is doing well and who needs a push.

**Live Demo:** [https://proboard.streamlit.app](https://proboard.streamlit.app)


https://github.com/user-attachments/assets/db630358-701a-4f9e-8e9a-d415e82b7f53


---

## 🛠️ The Tech Stack

I kept the stack relatively lightweight but robust enough to handle data ingestion, asynchronous API calls, and caching.

* **Frontend / UI:** [Streamlit](https://streamlit.io/) (with some custom CSS injections to make the sidebar and metrics look a bit more polished than the default theme).
* **Data Manipulation:** `pandas` and `numpy`.
* **API Fetching:** `aiohttp` and `asyncio` (Crucial for speed and rate-limiting).
* **Database / ORM:** SQLite mapped with `SQLAlchemy`.
* **Visualizations:** `plotly`.

---

```mermaid
flowchart TD

subgraph group_ingest["Input and fetching"]
  node_submissions["Student submissions"]
  node_cleaner["Ingestion and cleaning<br/>[cleaner.py]"]
  node_google_sheets["Google Sheets"]
  node_fetcher["Async stats fetcher<br/>[fetcher.py]"]
  node_coding_platforms["Coding platforms"]
end

subgraph group_analytics_ui["Analytics and dashboard"]
  node_dashboard["Streamlit dashboard<br/>[app.py]"]
  node_analytics["Cohort analytics<br/>[analytics.py]"]
  node_config["Runtime configuration<br/>[config.py]"]
end

subgraph group_persistence["Persistence"]
  node_db_access["Database access<br/>[database.py]"]
  node_models["Student and snapshot models<br/>[models.py]"]
  node_sqlite[("SQLite database<br/>[proboard.db]")]
end

subgraph group_alerts["Alerts"]
  node_notifier["At-risk notifier<br/>[notifier.py]"]
  node_smtp["SMTP email service"]
end

node_staff(("Staff user"))

node_staff -->|"uses"| node_dashboard
node_staff -->|"provides"| node_submissions
node_submissions -->|"ingests"| node_cleaner
node_cleaner -->|"downloads sheet"| node_google_sheets
node_cleaner -->|"returns clean data"| node_fetcher
node_dashboard -->|"invokes"| node_cleaner
node_dashboard -->|"invokes"| node_fetcher
node_fetcher -->|"fetches stats"| node_coding_platforms
node_dashboard -->|"persists and reads"| node_db_access
node_fetcher -->|"returns stats"| node_dashboard
node_db_access -->|"uses models"| node_models
node_db_access -->|"reads and writes"| node_sqlite
node_analytics -->|"queries snapshots"| node_models
node_dashboard -->|"builds leaderboard"| node_analytics
node_analytics -->|"returns analytics"| node_dashboard
node_dashboard -->|"uses settings"| node_config
node_fetcher -->|"uses limits"| node_config
node_notifier -->|"finds at-risk students"| node_analytics
node_notifier -->|"initializes database"| node_db_access
node_notifier -->|"logs sent alerts"| node_models
node_notifier -->|"sends email"| node_smtp

click node_cleaner "[https://github.com/b-mohid/proboard/blob/main/cleaner.py](https://github.com/b-mohid/proboard/blob/main/cleaner.py)"
click node_fetcher "[https://github.com/b-mohid/proboard/blob/main/fetcher.py](https://github.com/b-mohid/proboard/blob/main/fetcher.py)"
click node_dashboard "[https://github.com/b-mohid/proboard/blob/main/app.py](https://github.com/b-mohid/proboard/blob/main/app.py)"
click node_analytics "[https://github.com/b-mohid/proboard/blob/main/analytics.py](https://github.com/b-mohid/proboard/blob/main/analytics.py)"
click node_config "[https://github.com/b-mohid/proboard/blob/main/config.py](https://github.com/b-mohid/proboard/blob/main/config.py)"
click node_db_access "[https://github.com/b-mohid/proboard/blob/main/database.py](https://github.com/b-mohid/proboard/blob/main/database.py)"
click node_models "[https://github.com/b-mohid/proboard/blob/main/models.py](https://github.com/b-mohid/proboard/blob/main/models.py)"
click node_sqlite "[https://github.com/b-mohid/proboard/blob/main/data/proboard.db](https://github.com/b-mohid/proboard/blob/main/data/proboard.db)"
click node_notifier "[https://github.com/b-mohid/proboard/blob/main/notifier.py](https://github.com/b-mohid/proboard/blob/main/notifier.py)"

classDef toneNeutral fill:#f8fafc,stroke:#334155,stroke-width:1.5px,color:#0f172a
classDef toneBlue fill:#dbeafe,stroke:#2563eb,stroke-width:1.5px,color:#172554
classDef toneAmber fill:#fef3c7,stroke:#d97706,stroke-width:1.5px,color:#78350f
classDef toneMint fill:#dcfce7,stroke:#16a34a,stroke-width:1.5px,color:#14532d
classDef toneRose fill:#ffe4e6,stroke:#e11d48,stroke-width:1.5px,color:#881337
classDef toneIndigo fill:#e0e7ff,stroke:#4f46e5,stroke-width:1.5px,color:#312e81
classDef toneTeal fill:#ccfbf1,stroke:#0f766e,stroke-width:1.5px,color:#134e4a
class node_submissions,node_cleaner,node_google_sheets,node_fetcher,node_coding_platforms,node_staff toneBlue
class node_dashboard,node_analytics,node_config toneAmber
class node_db_access,node_models,node_sqlite toneMint
class node_notifier,node_smtp toneRose

```


## 🧠 How It Actually Works (The Walkthrough)

If you're looking through the code, here is a breakdown of how the data flows through the app. 

### 1. Data Ingestion & Cleaning (`cleaner.py`)
The app accepts either a direct file upload or a public Google Sheet URL. 
Students are notorious for pasting messy URLs (e.g., adding trailing slashes, random query parameters, or accidentally linking the 'badges' page instead of their main profile). The cleaner script uses regular expressions to strip out HTML/XSS payloads and strictly extracts just the username handle from whatever link they provided.

### 2. The Fetcher Engine (`fetcher.py`)
This was the trickiest part to get right. If you send 200+ requests to LeetCode's GraphQL API and HackerRank's REST API in a split second, they will assume you are a bot doing a DDoS attack and slap you with an HTTP 429 (Too Many Requests) or just ban your IP.

To fix this, I used `aiohttp` with `asyncio.Semaphore` to limit concurrent requests. If the script hits a rate limit, it catches it and applies exponential backoff (waiting a bit longer before trying again) instead of crashing the whole dashboard. It returns zeroes for private or broken profiles instead of throwing unhandled exceptions.

### 3. Database Caching (`database.py` & `models.py`)
We don't want to ping the APIs every single time someone refreshes the Streamlit page. 
Once the fetcher gets the data, SQLAlchemy bulk-upserts it into a local SQLite database (`proboard.db`). It stores the student info and a daily snapshot of their stats (`daily_stats` table). This allows us to calculate things like "7-Day Velocity" (how many problems they solved this week compared to last week).

### 4. The Analytics & Intervention Panel (`analytics.py` & `app.py`)
The main dashboard shows the global leaderboard and Plotly charts breaking down platform affinity (e.g., who prefers LeetCode vs HackerRank). 

My favorite part is the **Intervention Panel**. It filters the dataset to show actionable items:
* **Low Performers:** Students who haven't solved many problems.
* **Missing Profiles:** Students who forgot to submit their links.
* **API Failures:** Profiles that threw an error (usually means they set their LeetCode profile to private, or they typo'd their username).
* **Custom Filter:** A dual-ended slider to dynamically search for students who have solved within a specific range of problems (e.g., 60 to 80 problems).

### 5. Automated Alerts (`notifier.py`)
There is a standalone script that can be hooked up to a cron job. It checks the database for "at-risk" students (e.g., 0 velocity over 7 days) and sends them a polite, automated HTML email via `smtplib` reminding them to practice. It has an idempotency table (`email_log`) so it never accidentally spams a student twice in one day.

---

## 💻 Local Setup

If you want to run this yourself, grab the code and set up a virtual environment.

1. **Clone and install dependencies:**
   ```bash
   git clone <your-repo-link>
   cd proboard
   pip install -r requirements.txt
   ```

2. **Set up environment variables:**
   Create a `.env` file in the root directory. You'll need this for the email notifier and Google Sheets integration.
   ```env
   # .env
   GOOGLE_SHEET_ID=your_sheet_id_here
   HR_WEIGHT=0.5
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=your_email@gmail.com
   SMTP_PASSWORD=your_app_password
   ```

3. **Run the Streamlit App:**
   ```bash
   streamlit run app.py
   ```
   The app will spin up on `http://localhost:8501`. 

4. **Testing the Notifier (Optional):**
   If you want to test the email alerts without actually bothering anyone, use the dry-run flag:
   ```bash
   python notifier.py --dry
   ```

---
*Feel free to poke around the code, fork it, or submit a PR if you find a way to optimize the GraphQL queries further!*
