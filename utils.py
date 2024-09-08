import asyncio, json, markdown
from PIL import Image
from quart_motor import Motor

mongo = Motor()
homepage_data = {}
hq_leadership = []
national_leadership = []
discord = None

department_list = ["Officers", "Chiefs of Staff", "Communications", "Environmental Education", "Finance", "Advocacy", "Public Relations", "Volunteer"]

async def cache_loop():
    while True:
        await cache_data()
        await asyncio.sleep(300)# Run every 5 minutes

async def cache_data():
    global homepage_data
    global hq_leadership
    global national_leadership

    if mongo.db is None:
        data = json.loads(open("sample-data.json").read())
        homepage_data = data["homepage"]
        hq_leadership = data["hq_leadership"]
        national_leadership = data["national_leadership"]
    else:

        homepage_data = await mongo.db.homepage.find_one({})
        homepage_data["announcement"] = markdown.markdown(homepage_data["announcement"])
        homepage_data["announcement"] = homepage_data["announcement"].replace("<p>", "").replace("</p>", "").replace("<a ", "<a target='_blank' rel='noopener' ")

        hq_leadership = await mongo.db.hq_leadership.find_one({}, {"_id": False})
        for department_name in hq_leadership:
            hq_leadership[department_name].sort(key=lambda hq_leader: int(hq_leader["id"]))

        national_leadership = await mongo.db.national_leadership.find().to_list(None)
        national_leadership.sort(key=lambda nat_leader: int(nat_leader["_id"]))
