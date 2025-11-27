import os
import json
import requests
from flask import Flask, request, render_template_string
from google import genai

app = Flask(__name__)

# Gemini client
client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])


###############################################################
# 1. Upfluence Authentication
###############################################################

def get_upfluence_token():
    url = "https://identity.upfluence.co/oauth/token"

    payload = {
        "grant_type": "password",
        "username": os.environ.get("UPFLUENCE_USERNAME"),
        "password": os.environ.get("UPFLUENCE_PASSWORD")
    }

    headers = {"Content-Type": "application/json"}
    response = requests.post(url, json=payload, headers=headers)

    if response.status_code != 200:
        print("Upfluence auth failed:", response.text)
        return None

    return response.json().get("access_token")


###############################################################
# 2. Build Upfluence Query
###############################################################

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


###############################################################
# 3. Upfluence Search
###############################################################

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

    influencers = response.json().get("influencers", [])

    output = []
    for inf in influencers:
        output.append({
            "name": inf.get("name"),
            "followers": inf.get("community_size"),
            "location": inf.get("address"),
            "country": inf.get("country"),
            "avatar": inf.get("avatar_url")
        })

    return output


###############################################################
# 4. Tribe Extraction Prompt (ESCAPED BRACES)
###############################################################

TRIBE_PROMPT = """
Extract a tribe profile for Instagram handle: {handle}

Output ONLY JSON like this:
{{
  "niche": "fashion",
  "location": "London",
  "tier": "micro"
}}
"""


###############################################################
# 5. Tier to Follower Range
###############################################################

def tier_to_range(tier):
    tier = tier.lower()
    if "nano" in tier:
        return 1000, 10000
    if "micro" in tier:
        return 10000, 100000
    if "macro" in tier:
        return 100000, 1000000
    return 1000, 2000000


###############################################################
# 6. HTML Interface
###############################################################

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head><title>YSR Influencer Tool</title></head>
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


###############################################################
# 7. MAIN ROUTE
###############################################################

@app.route("/", methods=["GET", "POST"])
def home():
    result = ""

    if request.method == "POST":
        handle = request.form.get("handle")

        # A. TRIBE EXTRACTION
        raw = client.models.generate_content(
            model="models/gemini-1.5-flash",
            contents=TRIBE_PROMPT.format(handle=handle)
        ).text

        clean = raw.strip().replace("```", "").replace("json", "")

        try:
            tribe = json.loads(clean)
        except:
            tribe = {"niche": "lifestyle", "location": "", "tier": "micro"}

        # follower ranges
        fmin, fmax = tier_to_range(tribe.get("tier", "micro"))
        tribe["follower_min"] = fmin
        tribe["follower_max"] = fmax

        # B. UPFLUENCE SEARCH
        creators = search_upfluence_for_tribe(tribe)

        # C. FINAL ANALYSIS PROMPT (NO .format() JSON ISSUES)
        final_prompt = f"""
Analyse Instagram handle: {handle}

Tribe:
{json.dumps(tribe)}

Real influencers from Upfluence:
{json.dumps(creators)}

Give:
1. Account insights
2. Influencer tribes
3. A practical influencer strategy
"""

        output = client.models.generate_content(
            model="models/gemini-1.5-flash",
            contents=final_prompt
        ).text

        result = output

    return render_template_string(HTML_TEMPLATE, result=result)


###############################################################
# 8. ENTRYPOINT FOR CLOUD RUN
###############################################################

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
