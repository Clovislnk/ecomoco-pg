import asyncio, aiohttp, datetime, logging, os, sass, sys, utils, re
from dotenv import load_dotenv
from quart import Quart, redirect, render_template, request, send_from_directory, Response, session, url_for
from quart_discord import DiscordOAuth2Session, Unauthorized
from quart_rate_limiter import RateLimiter, rate_limit
from oauthlib.oauth2.rfc6749.errors import InvalidGrantError

app = Quart(__name__)
rate_limiter = RateLimiter(app)

load_dotenv()# Loads .env file into environment variables
sass.compile(dirname=('static', 'static'), output_style='compressed')# Compiles .scss > .css

if os.environ.get("MONGO_URI") is not None:# MongoDB connection
    app.config["MONGO_URI"] = os.environ.get("MONGO_URI")
    utils.mongo.init_app(app)
else:
    logging.info("No MONGO_URI environment variable found, skipping MongoDB connection")

if os.environ.get("DISCORD_CLIENT_SECRET") is not None:# Discord OAuth2
    app.secret_key = os.environ.get("SECRET_KEY") or os.urandom(48)
    app.config["DISCORD_CLIENT_ID"] = 1128107323458592859
    app.config["DISCORD_CLIENT_SECRET"] = os.environ.get("DISCORD_CLIENT_SECRET")
    app.config["DISCORD_BOT_TOKEN"] = os.environ.get("DISCORD_BOT_TOKEN")
    app.config["DISCORD_REDIRECT_URI"] = "https://ecomoco.co/oauth-callback" if sys.platform == "linux" else "http://localhost:8500/oauth-callback"
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"# Required due to proxy
    utils.discord = DiscordOAuth2Session(app)

app.url_map.strict_slashes = False
app.jinja_env.lstrip_blocks = True
app.jinja_env.trim_blocks = True

# -- Load Blueprints --

from blueprints.about import app as about_blueprint
from blueprints.dashboard import app as dashboard_blueprint
from blueprints.discord_oauth import app as discord_oauth_blueprint
from blueprints.static import app as static_blueprint

app.register_blueprint(about_blueprint)
app.register_blueprint(dashboard_blueprint)
app.register_blueprint(discord_oauth_blueprint)
app.register_blueprint(static_blueprint)

# -- Before Serving Requests --

@app.before_serving
async def load_data():
    app.client = aiohttp.ClientSession()
    asyncio.ensure_future(utils.cache_loop())

@app.before_request
async def path_redirects():
    path = request.path.lower()# case insensitive for requests
    if path != '/' and path.endswith('/'):# trailing slash
        path = path[:-1]
    if path.endswith('.html'):# removes .html from requests
        path = path[:-5]
    if path == '/index':# /index -> /
        path = '/'
    if path != request.path:# redirect if something has changed
        return redirect(path, 301)

# -- Routes --

@app.route("/")
async def homepage():
    return await render_template("homepage.jinja2", data=utils.homepage_data)

@app.route("/chapters")
async def chapters():
    return await render_template("chapters.jinja2", chapters_count=utils.homepage_data["chapters"])

@app.route("/get-involved")
async def get_involved():
    return await render_template("get-involved.jinja2")

# -- Feedback Form --

@app.route("/feedback-form", methods=["POST"])
@rate_limit(2, datetime.timedelta(minutes=5))
async def feedback_form():

    try:
        form_data = await request.json
    except:
        return Response("Failed to parse form data", status=400)

    # Check for empty fields & invalid data
    if form_data["email"] == "" or form_data["comments"] == "":
        return Response("Please fill out all fields", status=400)

    if re.search(r"[^@]+@[^@]+\.[^@]+", form_data["email"]) is None:
        return Response("Invalid email address.", status=400)

    if len(form_data["email"]) > 100:
        return Response("Email must be 100 characters or less.", status=400)

    if len(form_data["comments"]) > 500:
        return Response("Comments must be 500 characters or less.", status=400)

    # Check for Captcha
    r = await app.client.post("https://challenges.cloudflare.com/turnstile/v0/siteverify", headers={"Content-Type": "application/json"},
                          json={"response": form_data.pop("cf-turnstile-response"), "secret": os.environ.get("CLOUDFLARE_TURNSTILE")})

    if r.status != 200:
        return Response("Failed to verify captcha. Please recomplete the captcha and try again.", status=400)

    cloudflare_data = await r.json()
    if cloudflare_data["success"] != True:
        return Response("Failed to verify captcha. Please recomplete the captcha and try again.", status=400)

    # Send to Discord
    r2 = await app.client.post(os.environ.get("WEBHOOK"), headers={"Content-Type": "application/json"},
                                json={"embeds": [{"title":"New Website Feedback","description":f"> **IP:** {request.headers.getlist('X-Forwarded-For')[0]}\n> **Page:** {request.referrer}","color":7451903,"fields":[{"name":"Email","value":form_data["email"]},{"name":"Comments","value":form_data["comments"]}]}]})

    if r2.status != 204:
        logging.critical(f"Failed to send feedback to Discord: {r2.status}")
        logging.critical(await r2.text())
        return Response("Failed to send feedback to database. Please try again later.", status=400)

    return Response("Feedback submitted successfully. Thank you!", status=200)

# -- Error Handlers --

@app.errorhandler(Unauthorized)
async def redirect_unauthorized(e):
    return redirect(url_for("discord_oauth.oauth_login"))

@app.errorhandler(InvalidGrantError)
async def redirect_invalid_grant(e):
    return redirect(url_for("discord_oauth.oauth_login"))

@app.errorhandler(404)
async def page_not_found(error):
    if request.path in ["/favicon.ico", "/apple-touch-icon.png", "/browserconfig.xml"]:# Favicons!
        return await app.send_static_file("favicons" + request.path)
    return await render_template("404.jinja2"), 404

@app.errorhandler(429)
async def too_many_requests(error):
    return "Slow down! You're making too many requests to the server. Please try again later.", 429

@app.errorhandler(500)
async def internal_server_error(error):
    # if sys.platform == "linux": # This feature gets spammed because of favicon requests, etc.
    #     resp = await app.client.post(os.environ.get("WEBHOOK"), json={"content": f":warning: Internal Server Error (500) on Production: [`{request.path}`](https://ecomoco.co/{request.path})"})
    #     logging.info(f"Sent error webhook: {resp.status}")
    return "<h1>500 Internal Server Error</h1><p>Something went wrong on our end. We've been notified and will fix it as soon as possible.</p>", 500

if __name__ == "__main__":
    app.run(
            host='0.0.0.0',
            port=8500,
            use_reloader=True,
            debug=True
        )
