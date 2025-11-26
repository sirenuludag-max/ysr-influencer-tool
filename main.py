import os
from flask import Flask, request, render_template_string
from google import genai

app = Flask(__name__)

client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>YSR Influencer Tool</title>
</head>
<body>
    <h2>Influencer Tribe Builder</h2>
    <form method="post">
        <input type="text" name="handle" placeholder="Instagram handle">
        <button type="submit">Analyse</button>
    </form>
    <pre>{{ result }}</pre>
</body>
</html>
"""

PROMPT = """
[PASTE YOUR FULL GEMINI PROMPT HERE]
Use this Instagram handle: {handle}
"""

@app.route("/", methods=["GET", "POST"])
def home():
    result = ""
    if request.method == "POST":
        handle = request.form.get("handle")
        full_prompt = PROMPT.format(handle=handle)
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=full_prompt
        )
        result = response.text
    return render_template_string(HTML_TEMPLATE, result=result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
