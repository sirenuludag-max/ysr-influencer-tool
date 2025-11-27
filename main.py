import os
import json
import requests
from flask import Flask, request, render_template_string
from google import genai

app = Flask(__name__)

# Initialize Gemini client
client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])


####################################################
# 1. Upfluence Authentication
####################################################

def get_upfluence_token():
    url = "https://identity.upfluence.co/oauth/token"

    payload = {
        "grant_type": "password",
        "username": os.environ["UPFLUENCE_USERNAME"],
        "password": os.environ["UPFLUENCE_PASSWORD"]
    }

    headers = {"Content-Type": "application/json"}
    response = requests.post(url, json=payload, headers=headers)

    if response.status_code != 200:
        print("Upfluence auth failed:", response.text)
        return None

    return response.json().get("access_token")


####################################################
# 2. Build Upfluence Filters Based on Tribe Data
####################################################

def build_upfluence_payload(tribe_data):
    criterias = []
    filters = []

    niche = tribe_data.get("niche", "")
    location = tribe_data.get("location", "")
    follower_min = tribe_data.get("follower_min", 0)
    follower_max = tribe_data.get("follower_max", 5000000)

    if niche:
        criterias.append({
            "field": "all",
            "type": "should",
            "weight": 1,
            "value": niche
        })

    filters.append({
        "type": "int",
        "field": "instagram.followers",
        "order": ">",
        "value": follower_min
    })

    filters.append({
        "type": "int",
        "field": "instagram.followers",
        "order": "<",
        "value": follower_max
    })

    if location:
        filters.append({
            "type": "geocoded",
            "field": "influencer.geo_coordinates",
            "value": location,
            "radius": 100
        })

    return {
        "ordering": {"value": "relevancy", "direction": "desc"},
        "criterias": criterias,
        "filters": filters
    }


####################################################
# 3. Upfluence Influencer Search
####################################################

def search_upfluence_for_tribe(tribe_data):
    token = get_upfluence_token()
    if not token:
        return []

    payload = build_upfluence_payload(tribe_data)
    url = "https://api.upfluence.co/v1/matches?page=1&per_page=20"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    response = requests.post(url, json=payload, headers=headers)

    if response.status_code != 200:
        print("Upfluence search failed:", response.text)
        return []

    data = response.json()
    influencers = data.get("influencers", [])

    output = []
    for inf in influencers:
        output.append({
            "name": inf.get("name"),
            "id": inf.get("id"),
            "location": inf.get("address"),
            "country": inf.get("country"),
            "followers": inf.get("community_size"),
            "avatar": inf.get("avatar_url")
        })

    return output


####################################################
# 4. Tribe Extraction Prompt
####################################################

TRIBE_EXTRACTION_PROMPT = """
From the Instagram handle {handle}, infer:
1. Likely niche (one or two words)
2. Likely audience location (city or country)
3. Likely follower tier: nano, micro, macro

Output ONLY valid JSON:
{
  "niche": "...",
  "location": "...",
  "tier": "..."
}
"""


####################################################
# 5. Final Analysis Prompt
####################################################

FINAL_ANALYSIS_PROMPT = """
You are an influencer marketing analysis engine.

Analyse this Instagram account: {handle}

Use these tribe characteristics:
{tribe_info}

Use ONLY these real influencers from Upfluence:
{creators}

Do not invent influencer names, handles, or stats.
Every influencer MUST come from Upfluence.

Provide:
1. Account analysis
2. Influencer tribes
3. Recommended real influencers
4. A mini strategy
"""


####################################################
# 6. Convert tier to follower ranges
####################################################

def tier_to_range(tier):
    tier = tier.lower()
    if "nano" in tier:
        return 1000, 10000
    if "micro" in tier:
        return 10000, 100000
    if "macro" in tier:
        return 100000, 1000000
    return 1000, 2000000


####################################################
# 7. HTML Template
####################################################

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>YSR Influencer Tool</title>
</head>
<body>
    <h2>Influencer Tribe Builder</h2>

    <form method="post">
        <input type="text" name="handle" placeholder="Instagram handle" required>
        <button type="submit">Analyse</button>
    </form>

    <hr>
    <pre>{{ result }}</pre>
</body>
</html>
"""


####################################################
# 8. Main Route
####################################################

@app.route("/", methods=["GET", "POST"])
def home():
    result = ""

    if request.method == "POST":
        handle = request.form.get("handle")

        # Step A - extract tribe characteristics
        raw_json = client.generate_content(
            model="gemini-1.5-flash",
            contents=TRIBE_EXTRACTION_PROMPT.format(handle=handle)
        ).text

        tribe_clean = raw_json.strip().replace("```", "").replace("json", "")

        try:
            tribe_data = json.loads(tribe_clean)
        except:
            tribe_data = {
                "niche": "lifestyle",
                "location": "",
                "tier": "micro"
            }

        follower_min, follower_max = tier_to_range(tribe_data.get("tier", "micro"))
        tribe_data["follower_min"] = follower_min
        tribe_data["follower_max"] = follower_max

        # Step B - real influencer search
        creators = search_upfluence_for_tribe(tribe_data)

        # Step C - final analysis
        full_prompt = FINAL_ANALYSIS_PROMPT.format(
            handle=handle,
            tribe_info=tribe_data,
            creators=creators
        )

        try:
            response = client.generate_content(
                model="gemini-1.5-flash",
                contents=full_prompt
            )
            result = response.text
        except Exception as e:
            result = f"Gemini error: {e}"

    return render_template_string(HTML_TEMPLATE, result=result)


####################################################
# 9. Entrypoint for Cloud Run
####################################################

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
